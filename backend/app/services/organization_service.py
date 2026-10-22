"""Tenant-serialized organization changes with atomic revocation and audit."""
import asyncio
from sqlalchemy import select, delete, update
from sqlalchemy.exc import IntegrityError
from ..core.errors import AppException, ErrorCode
from ..models.identity import (OAUser, OADepartment, OAPosition, OAMembership,
    OARole, OAUserRole, OAPermission, OARolePermission, OAAuthSession)
from .identity_service import audit, lock_tenant, normalize, utcnow
from .credential_service import hash_password
from .authorization_service import require_fresh_identity, require_permission

BUSINESS_RESOURCES = ('meeting', 'document', 'email', 'work_task', 'report', 'contract', 'thread', 'task')
RESOURCES = (*BUSINESS_RESOURCES, 'organization', 'leave', 'approval', 'workflow', 'leave_balance', 'workflow_admin','reimbursement','ticket','ticket_handle','ticket_admin','notification','notification_admin')


def invalid(message):
    return AppException(ErrorCode.BAD_REQUEST, message, http_status=422)


async def _actor(session, actor, action='write'):
    actor = await require_fresh_identity(actor, session=session)
    if actor.data_scope.get('identity_provider') != 'builtin':
        raise AppException(ErrorCode.FORBIDDEN, '组织管理仅适用于正式账号模式', http_status=403)
    require_permission(actor, 'organization', action)
    return actor


async def _manage(session, actor):
    await lock_tenant(session, actor.tenant_id)
    # Management is uncommon and can affect every member of a role or department.
    # Use one deterministic lock order, shared with business commit checks.
    await session.scalars(select(OAUser).where(OAUser.tenant_id == actor.tenant_id)
        .order_by(OAUser.id).with_for_update().execution_options(populate_existing=True))
    return await _actor(session, actor)


async def _target(session, model, target_id, tenant, enabled=False):
    row = await session.scalar(select(model).where(model.id == target_id, model.tenant_id == tenant))
    if row is None:
        raise invalid('目标不存在或不属于当前组织')
    if enabled and (getattr(row, 'status', 'active') != 'active' or not getattr(row, 'enabled', True)):
        raise invalid('不能关联已停用的对象')
    return row


async def _finish(session, actor, action, target):
    audit(session, actor.user_id, action, target)
    # _manage holds the actor row lock and checked authority before an intentional
    # self lifecycle change; that same transaction may now revoke its own session.
    session.info.get('identity_actors', {}).pop(actor.user_id, None)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise invalid('名称或账号已存在，或关联对象无效') from None


async def _bump(session, user, *, revoke=False):
    user.authorization_version += 1
    if revoke:
        user.auth_version += 1
        await session.execute(update(OAAuthSession).where(OAAuthSession.user_id == user.id)
            .values(revoked_at=utcnow()))


async def _permission_ids(session, permissions):
    result = []
    for p in permissions:
        resource, action, scope = p['resource'], p['action'], p['scope']
        if resource not in RESOURCES:
            raise invalid('不支持的权限资源')
        row = await session.scalar(select(OAPermission).where(OAPermission.resource == resource,
            OAPermission.action == action, OAPermission.scope == scope))
        if not row:
            row = OAPermission(resource=resource, action=action, scope=scope)
            session.add(row)
            await session.flush()
        result.append(row.id)
    return set(result)


async def _employee_role(session, tenant):
    role = await session.scalar(select(OARole).where(OARole.tenant_id == tenant, OARole.code == 'employee'))
    if not role:
        role = OARole(tenant_id=tenant, code='employee', name='员工')
        session.add(role)
        await session.flush()
        ids = await _permission_ids(session, [dict(resource=r, action=a, scope='self')
            for r in BUSINESS_RESOURCES for a in ('read', 'write')])
        session.add_all([OARolePermission(tenant_id=tenant, role_id=role.id, permission_id=i) for i in ids])
        await session.flush()
    return role


async def _user_view(session, row):
    membership = await session.get(OAMembership, (row.tenant_id, row.id))
    roles = list((await session.scalars(select(OAUserRole.role_id).where(
        OAUserRole.tenant_id == row.tenant_id, OAUserRole.user_id == row.id))).all())
    return dict(id=row.id, username=row.normalized_username, display_name=row.display_name,
        status=row.status, handoff_pending=row.handoff_pending, role_ids=roles,
        department_id=membership.department_id if membership else None,
        position_id=membership.position_id if membership else None,
        manager_id=membership.manager_id if membership else None)


async def overview(session, actor):
    actor = await _actor(session, actor, 'read')
    async def rows(model):
        return (await session.scalars(select(model).where(model.tenant_id == actor.tenant_id).order_by(model.id))).all()
    departments = [dict(id=r.id, name=r.name, parent_id=r.parent_id, enabled=r.enabled) for r in await rows(OADepartment)]
    positions = [dict(id=r.id, name=r.name, enabled=r.enabled) for r in await rows(OAPosition)]
    users = [await _user_view(session, r) for r in await rows(OAUser)]
    roles = []
    for r in await rows(OARole):
        permissions = (await session.execute(select(OAPermission.resource, OAPermission.action, OAPermission.scope)
            .join(OARolePermission, OARolePermission.permission_id == OAPermission.id)
            .where(OARolePermission.tenant_id == actor.tenant_id, OARolePermission.role_id == r.id))).all()
        roles.append(dict(id=r.id, code=r.code, name=r.name,
            permissions=[dict(resource=p[0], action=p[1], scope=p[2]) for p in permissions]))
    return dict(departments=departments, positions=positions, users=users, roles=roles, resources=RESOURCES)


async def save_department(session, actor, payload, department_id=None):
    actor = await _manage(session, actor)
    row = await _target(session, OADepartment, department_id, actor.tenant_id) if department_id else OADepartment(tenant_id=actor.tenant_id)
    if payload.parent_id:
        current = await _target(session, OADepartment, payload.parent_id, actor.tenant_id, True)
        seen = {row.id} if row.id else set()
        while current:
            if current.id in seen:
                raise invalid('部门层级不能形成循环')
            seen.add(current.id)
            current = await _target(session, OADepartment, current.parent_id, actor.tenant_id) if current.parent_id else None
    if department_id and not payload.enabled:
        members = await session.scalar(select(OAMembership.user_id).where(OAMembership.tenant_id == actor.tenant_id,
            OAMembership.department_id == row.id).limit(1))
        children = await session.scalar(select(OADepartment.id).where(OADepartment.tenant_id == actor.tenant_id,
            OADepartment.parent_id == row.id).limit(1))
        if members or children:
            raise invalid('部门仍被成员或下级部门引用，请先调整归属')
    row.name, row.parent_id, row.enabled = payload.name.strip(), payload.parent_id, payload.enabled
    session.add(row)
    await session.flush()
    result = dict(id=row.id, name=row.name, parent_id=row.parent_id, enabled=row.enabled)
    await _finish(session, actor, 'organization.department', row.id)
    return result


async def save_position(session, actor, payload, position_id=None):
    actor = await _manage(session, actor)
    row = await _target(session, OAPosition, position_id, actor.tenant_id) if position_id else OAPosition(tenant_id=actor.tenant_id)
    if position_id and not payload.enabled and await session.scalar(select(OAMembership.user_id).where(
            OAMembership.tenant_id == actor.tenant_id, OAMembership.position_id == row.id).limit(1)):
        raise invalid('岗位仍被成员引用，请先调整归属')
    row.name, row.enabled = payload.name.strip(), payload.enabled
    session.add(row)
    await session.flush()
    result = dict(id=row.id, name=row.name, enabled=row.enabled)
    await _finish(session, actor, 'organization.position', row.id)
    return result


async def _assign(session, actor, user, payload):
    roles = [await _target(session, OARole, rid, actor.tenant_id) for rid in set(payload.role_ids or [])]
    admin = await session.scalar(select(OARole).where(OARole.tenant_id == actor.tenant_id, OARole.code == 'admin'))
    if admin and not (user.status == 'active' and admin.id in {r.id for r in roles}):
        others = await session.scalar(select(OAUser.id).join(OAUserRole, OAUserRole.user_id == OAUser.id).where(
            OAUser.tenant_id == actor.tenant_id, OAUser.status == 'active', OAUser.id != user.id,
            OAUserRole.tenant_id == actor.tenant_id, OAUserRole.role_id == admin.id).limit(1))
        if not others:
            raise invalid('必须保留至少一个启用的系统管理员')
    membership = await session.get(OAMembership, (actor.tenant_id, user.id))
    if payload.department_id:
        await _target(session, OADepartment, payload.department_id, actor.tenant_id, True)
        if payload.position_id:
            await _target(session, OAPosition, payload.position_id, actor.tenant_id, True)
        manager = payload.manager_id
        visited = {user.id}
        while manager:
            if manager in visited:
                raise invalid('直属上级关系不能形成循环')
            visited.add(manager)
            await _target(session, OAUser, manager, actor.tenant_id, True)
            upper = await session.get(OAMembership, (actor.tenant_id, manager))
            manager = upper.manager_id if upper else None
        if not membership:
            membership = OAMembership(tenant_id=actor.tenant_id, user_id=user.id)
            session.add(membership)
        membership.department_id, membership.position_id, membership.manager_id = payload.department_id, payload.position_id, payload.manager_id
    else:
        if payload.position_id or payload.manager_id:
            raise invalid('请先指定成员所属部门')
        if membership:
            await session.delete(membership)
    await session.execute(delete(OAUserRole).where(OAUserRole.tenant_id == actor.tenant_id, OAUserRole.user_id == user.id))
    session.add_all([OAUserRole(tenant_id=actor.tenant_id, user_id=user.id, role_id=r.id) for r in roles])


async def create_user(session, actor, payload):
    actor = await _manage(session, actor)
    username = normalize(payload.username)
    if not username or await session.scalar(select(OAUser.id).where(OAUser.tenant_id == actor.tenant_id, OAUser.normalized_username == username)):
        raise invalid('账号已存在或格式无效')
    if payload.role_ids is None:
        payload = payload.model_copy(update={'role_ids': [(await _employee_role(session, actor.tenant_id)).id]})
    row = OAUser(tenant_id=actor.tenant_id, normalized_username=username, display_name=payload.display_name.strip(),
        password_hash=await asyncio.to_thread(hash_password, payload.password.get_secret_value()))
    session.add(row)
    await session.flush()
    await _assign(session, actor, row, payload)
    await session.flush()
    result = await _user_view(session, row)
    await _finish(session, actor, 'organization.user_create', row.id)
    return result


async def update_user(session, actor, user_id, payload):
    actor = await _manage(session, actor)
    user = await _target(session, OAUser, user_id, actor.tenant_id)
    changed_status = user.status != payload.status
    user.display_name, user.status = payload.display_name.strip(), payload.status
    if user.status == 'disabled':
        user.handoff_pending = True
    await _assign(session, actor, user, payload)
    await _bump(session, user, revoke=changed_status)
    await session.flush()
    result = await _user_view(session, user)
    await _finish(session, actor, 'organization.user_update', user.id)
    return result


async def reset_password(session, actor, user_id, payload):
    actor = await _manage(session, actor)
    user = await _target(session, OAUser, user_id, actor.tenant_id)
    user.password_hash = await asyncio.to_thread(hash_password, payload.password.get_secret_value())
    user.failed_attempts, user.locked_until = 0, None
    await _bump(session, user, revoke=True)
    await _finish(session, actor, 'organization.reset_password', user.id)


async def save_role(session, actor, payload, role_id=None):
    actor = await _manage(session, actor)
    role = await _target(session, OARole, role_id, actor.tenant_id) if role_id else OARole(tenant_id=actor.tenant_id, code=payload.code)
    if role.code == 'admin':
        expected = {('organization', 'read'), ('organization', 'write')}
        if not role_id or not expected.issubset({(p.resource, p.action) for p in payload.permissions}):
            raise invalid('系统管理员必须保留组织读取和管理权限')
    if role_id and role.code != payload.code:
        raise invalid('角色编码创建后不能修改')
    role.name = payload.name.strip()
    session.add(role)
    await session.flush()
    ids = await _permission_ids(session, [p.model_dump() for p in payload.permissions])
    await session.execute(delete(OARolePermission).where(OARolePermission.tenant_id == actor.tenant_id, OARolePermission.role_id == role.id))
    session.add_all([OARolePermission(tenant_id=actor.tenant_id, role_id=role.id, permission_id=i) for i in ids])
    affected = (await session.scalars(select(OAUser).join(OAUserRole, OAUserRole.user_id == OAUser.id).where(
        OAUser.tenant_id == actor.tenant_id, OAUserRole.tenant_id == actor.tenant_id, OAUserRole.role_id == role.id))).all()
    for user in affected:
        await _bump(session, user)
    await _finish(session, actor, 'organization.role', role.id)
    return dict(id=role.id)
