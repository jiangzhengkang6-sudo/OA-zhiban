"""Transactional local accounts, revocable sessions and live identity snapshots."""
import asyncio
import hashlib
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update, text
from sqlalchemy.dialects.postgresql import insert
from ..core.config import get_settings
from ..core.context import CurrentUser
from ..core.errors import AppException, ErrorCode
from ..models.identity import (OAUser, OAMembership, OARole, OAPermission, OAUserRole,
                               OARolePermission, OAAuthSession, OAAuthThrottle)
from ..models.audit_event import AuditEvent
from ..schemas.identity import AccessGrant, CurrentUserView, PermissionView
from .credential_service import hash_password, verify_password, encode_access, decode_access


def utcnow():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def normalize(value):
    return unicodedata.normalize('NFKC', value).strip().casefold()


def unauthorized():
    return AppException(ErrorCode.UNAUTHORIZED, '账号、密码或会话无效，请重新登录', http_status=401)


async def lock_tenant(session, tenant):
    # All account/role changes serialize against the same transaction-scoped lock.
    await session.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'), {'key': 'oa-identity:' + tenant})


def audit(session, actor_id, action, target_id, *, result='success'):
    session.add(AuditEvent(actor_id=actor_id, action=action, target_type='identity',
                           target_id=target_id, result=result))


async def bootstrap_admin(session, username, password, *, tenant_id='local'):
    await lock_tenant(session, tenant_id)
    admin_role = await session.scalar(select(OARole).where(OARole.tenant_id == tenant_id, OARole.code == 'admin'))
    if admin_role:
        raise AppException(ErrorCode.FORBIDDEN, '管理员已初始化，请使用组织管理建号', http_status=403)
    hashed = await asyncio.to_thread(hash_password, password)
    user = OAUser(tenant_id=tenant_id, normalized_username=normalize(username), display_name=username, password_hash=hashed)
    role = OARole(tenant_id=tenant_id, code='admin', name='系统管理员')
    session.add_all([user, role])
    await session.flush()
    session.add(OAUserRole(tenant_id=tenant_id, user_id=user.id, role_id=role.id))
    for resource in ('organization',):
        for action in ('read', 'write'):
            permission = await session.scalar(select(OAPermission).where(OAPermission.resource == resource, OAPermission.action == action, OAPermission.scope == 'department'))
            if permission is None:
                permission = OAPermission(resource=resource, action=action, scope='department')
                session.add(permission)
                await session.flush()
            session.add(OARolePermission(tenant_id=tenant_id, role_id=role.id, permission_id=permission.id))
    audit(session, user.id, 'identity.bootstrap', user.id)
    await session.commit()
    return user


async def current_identity(session, user):
    if user is None or user.status != 'active':
        raise unauthorized()
    roles = list((await session.scalars(select(OARole.code).join(OAUserRole, OAUserRole.role_id == OARole.id).where(
        OAUserRole.tenant_id == user.tenant_id, OAUserRole.user_id == user.id))).all())
    perms = (await session.execute(select(OAPermission.resource, OAPermission.action, OAPermission.scope)
        .join(OARolePermission, OARolePermission.permission_id == OAPermission.id)
        .join(OAUserRole, (OAUserRole.role_id == OARolePermission.role_id) & (OAUserRole.tenant_id == OARolePermission.tenant_id))
        .where(OAUserRole.user_id == user.id, OAUserRole.tenant_id == user.tenant_id).distinct())).all()
    membership = await session.get(OAMembership, (user.tenant_id, user.id))
    return CurrentUser(user_id=user.id, tenant_id=user.tenant_id, roles=roles,
        depts=[membership.department_id] if membership else [],
        data_scope={'identity_provider': 'builtin', 'display_name': user.display_name,
                    'permissions': [dict(resource=r, action=a, scope=s) for r,a,s in perms]},
        auth_version=user.auth_version, authorization_version=user.authorization_version)


def view(actor):
    return CurrentUserView(user_id=actor.user_id, display_name=actor.data_scope.get('display_name', actor.user_id),
                           roles=actor.roles, depts=actor.depts, permissions=actor.data_scope.get('permissions', []))


@dataclass(repr=False)
class IssuedSession:
    grant: AccessGrant
    refresh: str


async def issue(session, user, settings, *, family_id=None, expires=None):
    raw = secrets.token_urlsafe(48)
    row = OAAuthSession(tenant_id=user.tenant_id, user_id=user.id, family_id=family_id or str(uuid4()),
        refresh_digest=digest(raw), auth_version=user.auth_version,
        absolute_expires_at=expires or utcnow() + timedelta(days=settings.auth_refresh_days))
    session.add(row)
    await session.flush()
    actor = await current_identity(session, user)
    return IssuedSession(AccessGrant(access_token=encode_access(user.id, row.id, user.auth_version, settings),
                                     expires_in=settings.auth_access_seconds, user=view(actor)), raw)


async def throttle(session, source):
    key = digest(source)
    now = utcnow()
    await session.execute(insert(OAAuthThrottle).values(key=key, attempts=0, window_start=now).on_conflict_do_nothing())
    row = await session.scalar(select(OAAuthThrottle).where(OAAuthThrottle.key == key).with_for_update())
    if row.window_start < now - timedelta(minutes=15):
        row.attempts, row.window_start = 0, now
    row.attempts += 1
    if row.attempts > 60:
        await session.commit()
        raise unauthorized()


async def login(session, username, password, *, source, tenant_id=None, settings=None):
    settings = settings or get_settings()
    tenant_id = tenant_id or settings.auth_tenant_id
    await throttle(session, 'login:' + source)
    user = await session.scalar(select(OAUser).where(OAUser.tenant_id == tenant_id,
        OAUser.normalized_username == normalize(username)).with_for_update())
    # Equal-cost hashing for nonexistent accounts prevents a cheap username oracle.
    valid = await asyncio.to_thread(verify_password, password, user.password_hash) if user else False
    if user is None:
        await asyncio.to_thread(hash_password, 'unavailable-account-placeholder')
    now = utcnow()
    if not user or user.status != 'active' or (user.locked_until and user.locked_until > now) or not valid:
        if user and user.status == 'active' and (not user.locked_until or user.locked_until <= now):
            if user.locked_until:
                user.failed_attempts = 0
            user.failed_attempts += 1
            user.locked_until = now + timedelta(minutes=15) if user.failed_attempts >= 5 else None
        audit(session, user.id if user else None, 'identity.login', user.id if user else None, result='fail')
        await session.commit()
        raise unauthorized()
    user.failed_attempts, user.locked_until = 0, None
    issued = await issue(session, user, settings)
    audit(session, user.id, 'identity.login', user.id)
    await session.commit()
    return issued


async def rotate_refresh(raw, *, session, settings=None):
    settings = settings or get_settings()
    if not raw or len(raw) > 256:
        raise unauthorized()
    # Lock the account before session rows, matching disable/change-password lock order.
    prior = await session.scalar(select(OAAuthSession).where(OAAuthSession.refresh_digest == digest(raw)))
    if prior is None:
        raise unauthorized()
    user = await session.scalar(select(OAUser).where(OAUser.id == prior.user_id).with_for_update().execution_options(populate_existing=True))
    row = await session.scalar(select(OAAuthSession).where(OAAuthSession.id == prior.id).with_for_update().execution_options(populate_existing=True))
    if row.consumed_at or row.revoked_at:
        await session.execute(update(OAAuthSession).where(OAAuthSession.family_id == row.family_id).values(revoked_at=utcnow()))
        audit(session, user.id, 'identity.refresh_replay', user.id, result='fail')
        await session.commit()
        raise unauthorized()
    if user.status != 'active' or row.auth_version != user.auth_version or row.absolute_expires_at <= utcnow():
        raise unauthorized()
    row.consumed_at = utcnow()
    issued = await issue(session, user, settings, family_id=row.family_id, expires=row.absolute_expires_at)
    await session.commit()
    return issued


async def resolve_access(token, *, session, settings=None):
    try:
        claims = decode_access(token, settings or get_settings())
    except ValueError:
        raise unauthorized() from None
    row = await session.get(OAAuthSession, claims['sid'], populate_existing=True)
    user = await session.get(OAUser, claims['sub'], populate_existing=True)
    if not row or not user or row.user_id != user.id or row.revoked_at or row.consumed_at or row.absolute_expires_at <= utcnow() or row.auth_version != user.auth_version or claims['av'] != user.auth_version:
        raise unauthorized()
    actor = await current_identity(session, user)
    actor.session_id = row.id
    return actor


async def logout(raw, *, session):
    row = await session.scalar(select(OAAuthSession).where(OAAuthSession.refresh_digest == digest(raw or '')))
    if row:
        await session.scalar(select(OAUser).where(OAUser.id == row.user_id).with_for_update())
        await session.execute(update(OAAuthSession).where(OAAuthSession.family_id == row.family_id).values(revoked_at=utcnow()))
        audit(session, row.user_id, 'identity.logout', row.user_id)
    await session.commit()


async def change_password(session, actor, old_password, new_password):
    user = await session.scalar(select(OAUser).where(OAUser.id == actor.user_id).with_for_update().execution_options(populate_existing=True))
    if user.status != 'active' or not await asyncio.to_thread(verify_password, old_password, user.password_hash):
        raise unauthorized()
    user.password_hash = await asyncio.to_thread(hash_password, new_password)
    user.auth_version += 1
    await session.execute(update(OAAuthSession).where(OAAuthSession.user_id == user.id).values(revoked_at=utcnow()))
    audit(session, user.id, 'identity.change_password', user.id)
    await session.commit()
