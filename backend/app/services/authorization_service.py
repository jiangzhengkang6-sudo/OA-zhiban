"""Deny-by-default resource and tool decisions using refreshed authority facts."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from ..adapters.factory import get_adapter
from ..core.context import CurrentUser
from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..tools.registry import SCENE_TOOLS


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason_code: str
    resource_scope: dict
    tool_allowlist: frozenset[str]
    evaluated_at: datetime


async def require_fresh_identity(actor: CurrentUser, required_roles: Iterable[str] = (), *, session=None) -> CurrentUser:
    """Never trust a stale graph/JWT role snapshot for a new business action."""
    if actor is None:
        raise AppException(ErrorCode.UNAUTHORIZED, "请先登录", http_status=401)
    from ..providers.identity import IdentityResolver
    from ..core.config import get_settings
    if session is None:
        from ..db.session import async_session_factory
        async with async_session_factory() as db:
            return await require_fresh_identity(actor, required_roles, session=db)
    if get_settings().auth_provider == 'mock':
        try:
            context = get_adapter().get_user_context(actor.user_id)
        except Exception:
            raise AppException(ErrorCode.DEPENDENCY_FAILED, '身份权限暂不可用', http_status=502) from None
        fresh = CurrentUser(user_id=context.user_id, tenant_id=context.tenant_id, roles=list(context.roles),
                            depts=[context.dept_id], data_scope=context.data_scope) if context else None
    else:
        fresh = await IdentityResolver().resolve(actor.user_id, session=session)
    if fresh is None or actor.tenant_id != fresh.tenant_id:
        raise AppException(ErrorCode.FORBIDDEN, "无权访问该资源", http_status=403)
    if fresh.data_scope.get('identity_provider') == 'builtin':
        if actor.auth_version is not None and actor.auth_version != fresh.auth_version:
            raise AppException(ErrorCode.UNAUTHORIZED, '会话已失效', http_status=401)
        if actor.authorization_version is not None and actor.authorization_version != fresh.authorization_version:
            raise AppException(ErrorCode.FORBIDDEN, '权限已变化，请重新发起操作', http_status=403)
        if actor.session_id:
            from ..models.identity import OAAuthSession
            from .identity_service import utcnow, unauthorized
            row = await session.get(OAAuthSession, actor.session_id, populate_existing=True)
            if not row or row.revoked_at or row.consumed_at or row.absolute_expires_at <= utcnow():
                raise unauthorized()
        fresh.session_id = actor.session_id
        session.info.setdefault('identity_actors', {}).setdefault(fresh.user_id, fresh)
    if required_roles and not set(required_roles).intersection(fresh.roles):
        raise AppException(ErrorCode.FORBIDDEN, "无权执行此操作", http_status=403)
    return fresh


async def require_business_identity(actor, *, session=None):
    fresh = await require_fresh_identity(actor, session=session)
    if fresh.data_scope.get('identity_provider') != 'builtin' and not set(fresh.roles).intersection(
            {'employee', 'approver', 'admin', 'ops'}):
        raise AppException(ErrorCode.FORBIDDEN, '无权执行此操作', http_status=403)
    return fresh


def authorize_resource(actor: CurrentUser, tenant_id: str, owner_id: str, *, required_roles: Iterable[str] = ()) -> AuthorizationDecision:
    same_tenant = actor is not None and actor.tenant_id == tenant_id
    matching_role = bool(actor and set(required_roles).intersection(actor.roles))
    if actor and actor.data_scope.get('identity_provider') == 'builtin':
        matching_role = False
    allowed = bool(same_tenant and (actor.user_id == owner_id or matching_role or
                                    ("admin" in actor.roles and actor.data_scope.get("all"))))
    return AuthorizationDecision(allowed, "allowed" if allowed else "forbidden",
                                 actor.data_scope if allowed else {}, frozenset(), datetime.now(timezone.utc))


async def authorize_tool(actor: CurrentUser, scene: str, tool_name: str, *, session=None,
                   required_roles: Iterable[str] = (), policy_tools: Iterable[str] | None = None) -> AuthorizationDecision:
    require_ai_enabled()
    fresh = await require_fresh_identity(actor, required_roles, session=session)
    if fresh.data_scope.get('identity_provider') == 'builtin':
        if (scene == 'leave' and tool_name not in {'get_user_context', 'get_leave_balance', 'get_approval_route', 'create_or_update_oa_approval'}
                or scene == 'faq' and tool_name not in {'get_user_context', 'search_knowledge'}
                or scene == 'ticket' and tool_name not in {'get_user_context', 'create_or_merge_ticket', 'get_ticket_status'}):
            raise AppException(ErrorCode.DEPENDENCY_FAILED, '此工具尚未接通正式 OA 业务', http_status=503)
        require_permission(fresh, 'knowledge' if scene == 'faq' else scene,
            'write' if tool_name in {'create_or_update_oa_approval', 'create_or_merge_ticket', 'notify_user'} else 'read')
    allowed_tools = set(SCENE_TOOLS.get(scene, ()))
    if policy_tools is not None:
        allowed_tools.intersection_update(policy_tools)
    if (tool_name == "create_or_update_oa_approval" and "approver" not in fresh.roles
            and fresh.data_scope.get('identity_provider') != 'builtin'):
        allowed_tools.discard(tool_name)
    allowed = tool_name in allowed_tools
    if not allowed:
        raise AppException(ErrorCode.TOOL_NOT_ALLOWED, "工具在当前权限或策略范围内不可用", http_status=403)
    return AuthorizationDecision(True, "allowed", fresh.data_scope,
                                 frozenset(allowed_tools), datetime.now(timezone.utc))


def require_ai_enabled():
    from ..core.config import get_settings
    if not get_settings().ai_enabled:
        raise AppException(ErrorCode.DEPENDENCY_FAILED, '智能功能已关闭，请使用人工工作台', http_status=503)


def require_permission(actor, resource, action):
    if actor.data_scope.get('identity_provider') != 'builtin':
        return
    if not any(p['resource'] == resource and p['action'] == action for p in actor.data_scope.get('permissions', [])):
        raise AppException(ErrorCode.FORBIDDEN, '当前账号没有该操作权限', http_status=403)


async def verify_before_commit(session):
    await session.run_sync(verify_before_commit_sync)


def verify_before_commit_sync(session):
    from sqlalchemy import select
    from ..models.identity import OAUser, OAAuthSession
    from .identity_service import unauthorized, utcnow
    for actor in sorted(session.info.get('identity_actors', {}).values(), key=lambda a: a.user_id):
        expected = (actor.auth_version, actor.authorization_version)
        with session.no_autoflush:
            user = session.scalar(select(OAUser).where(OAUser.id == actor.user_id).with_for_update().execution_options(populate_existing=True))
            if not user or user.status != 'active' or (user.auth_version, user.authorization_version) != expected:
                raise unauthorized()
            if actor.session_id:
                row = session.get(OAAuthSession, actor.session_id, populate_existing=True)
                if not row or row.user_id != actor.user_id or row.revoked_at or row.consumed_at or row.absolute_expires_at <= utcnow():
                    raise unauthorized()


def resource_clause(actor, resource, owner_column, action='read'):
    """One scope predicate shared by collections and direct resource lookups."""
    from sqlalchemy import select, or_
    from ..models.identity import OAMembership
    require_permission(actor, resource, action)
    own = owner_column == actor.user_id
    if actor.data_scope.get('identity_provider') != 'builtin':
        return own
    permissions = actor.data_scope.get('permissions', [])
    if any(p['resource'] == resource and p['action'] == action and p['scope'] == 'department' for p in permissions):
        members = select(OAMembership.user_id).where(OAMembership.tenant_id == actor.tenant_id,
            OAMembership.department_id.in_(actor.depts))
        return or_(own, owner_column.in_(members))
    return own


def business_boundary(resource, action):
    """Also enforce authorization for direct service and tool invocations."""
    from functools import wraps
    def decorate(fn):
        @wraps(fn)
        async def wrapped(session, actor, *args, **kwargs):
            actor = await require_fresh_identity(actor, session=session)
            require_permission(actor, resource, action)
            result = await fn(session, actor, *args, **kwargs)
            await require_fresh_identity(actor, session=session)
            return result
        return wrapped
    return decorate
