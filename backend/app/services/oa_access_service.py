"""Current tenant/resource/scope authority for manual OA; no role-name bypass."""
from dataclasses import dataclass

from sqlalchemy import select
from ..core.context import CurrentUser
from ..core.errors import AppException, ErrorCode
from ..models.identity import OADepartment, OAMembership, OAUser
from .authorization_service import require_fresh_identity, require_permission

OA_RESOURCES = ('leave', 'approval', 'workflow', 'leave_balance', 'workflow_admin','reimbursement','ticket','ticket_handle','ticket_admin','notification','notification_admin','announcement','meeting')


def denied():
    return AppException(ErrorCode.FORBIDDEN, '无权访问或办理该业务', http_status=403)


def invalid(message):
    return AppException(ErrorCode.INVALID_STATE, message, http_status=422)


def revision_conflict():
    return AppException(ErrorCode.IDEMPOTENCY_CONFLICT, '内容已变化，请刷新后重试', http_status=409)


@dataclass(frozen=True)
class OAAccessTarget:
    tenant_id: str
    owner_id: str | None = None
    department_id: str | None = None


@dataclass(frozen=True)
class OAAccessContext:
    actor: CurrentUser
    target: OAAccessTarget


async def builtin_actor(db, actor):
    fresh = await require_fresh_identity(actor, session=db)
    if fresh.data_scope.get('identity_provider') != 'builtin':
        raise denied()
    return fresh


def department_permission(actor, resource, action):
    return any(p['resource'] == resource and p['action'] == action and p['scope'] == 'department'
               for p in actor.data_scope.get('permissions', []))


MANAGEMENT_RESOURCES = {'workflow', 'workflow_admin', 'leave_balance', 'ticket_admin', 'notification_admin'}


def organization_management(actor, resource, action):
    # Organization-wide administration requires both explicit grants, never a role name.
    return resource in MANAGEMENT_RESOURCES and department_permission(actor, resource, action) and any(
        p['resource'] == 'organization' and p['action'] == 'write' and p['scope'] == 'department'
        for p in actor.data_scope.get('permissions', []))


async def management_departments(db, actor, resource, action):
    require_permission(actor, resource, action)
    if not department_permission(actor, resource, action):
        raise denied()
    query = select(OADepartment.id).where(OADepartment.tenant_id == actor.tenant_id, OADepartment.enabled.is_(True))
    if not organization_management(actor, resource, action):
        query = query.where(OADepartment.id.in_(actor.depts))
    return list((await db.scalars(query)).all())


async def authorize_oa(db, actor, resource, action, *, target):
    actor = await builtin_actor(db, actor)
    if resource not in OA_RESOURCES or action not in {'read', 'write'} or target.tenant_id != actor.tenant_id:
        raise denied()
    require_permission(actor, resource, action)
    owner = target.owner_id == actor.user_id
    if resource=='notification' and not owner:
        raise denied()
    if resource in {'leave','reimbursement','ticket'} and action == 'write' and not owner:
        raise denied()
    department_only = resource in {'workflow', 'workflow_admin','ticket_admin','notification_admin','announcement'} or resource == 'leave_balance' and action == 'write'
    if owner and not department_only:
        return OAAccessContext(actor, target)
    if not target.department_id or not department_permission(actor, resource, action) or (
        target.department_id not in actor.depts and not organization_management(actor, resource, action)):
        raise denied()
    dept = await db.scalar(select(OADepartment).where(OADepartment.tenant_id == actor.tenant_id,
        OADepartment.id == target.department_id, OADepartment.enabled.is_(True)))
    if dept is None:
        raise denied()
    if target.owner_id:
        membership = await db.get(OAMembership, (actor.tenant_id, target.owner_id), populate_existing=True)
        if not membership or membership.department_id != target.department_id:
            raise denied()
    return OAAccessContext(actor, target)


async def tenant_row(db, model, actor, row_id, *, lock=False):
    query = select(model).where(model.id == row_id, model.tenant_id == actor.tenant_id).execution_options(populate_existing=True)
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise AppException(ErrorCode.NOT_FOUND, '记录不存在或不可访问', http_status=404)
    return row


async def user_department(db, tenant, user_id):
    membership = await db.get(OAMembership, (tenant, user_id), populate_existing=True)
    return membership.department_id if membership else None
