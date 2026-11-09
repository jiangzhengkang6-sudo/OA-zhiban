"""Deterministic workflow configuration and route compilation."""
import operator
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from uuid import uuid5, NAMESPACE_URL

from pydantic import BaseModel
from sqlalchemy import select
from ..models.identity import OAUser, OAMembership, OARole, OAUserRole, OAPosition, OADepartment
from ..models.oa_workflow import OAWorkflowDefinition, OAWorkflowVersion, OAWorkflowNode, OAWorkflowSeat
from ..schemas.oa_workflow import ValidatedDefinition, WorkflowSave
from .identity_service import current_identity, lock_tenant
from .authorization_service import require_permission
from .oa_access_service import (authorize_oa, OAAccessTarget, builtin_actor, tenant_row,
                               invalid, revision_conflict, user_department, department_permission, management_departments)
from .oa_command_service import OACommand, CommandOutcome, run_command, canonical_hash


def evaluate_condition(field, op, expected, values):
    actual = values[field]
    if field=='amount' and (isinstance(expected,dict) or isinstance(expected,list) and all(isinstance(v,dict) for v in expected)):
        expected=[v['amount_minor'] for v in expected] if op=='in' else expected['amount_minor']
    if isinstance(actual, date):
        expected = [date.fromisoformat(value) for value in expected] if op == 'in' else date.fromisoformat(expected)
    if op == 'in':
        return actual in expected
    operations = dict(eq=operator.eq, ne=operator.ne, lt=operator.lt,
                      le=operator.le, gt=operator.gt, ge=operator.ge)
    return operations[op](actual, expected)


WorkflowDefinitionInput = WorkflowSave


class PublishedWorkflowView(BaseModel):
    id: str
    definition_id: str
    version: int
    form_version: int
    rule_version: int
    workflow_hash: str
    form_hash: str
    rule_hash: str
    package: dict


@dataclass
class RoutePlan:
    nodes: list
    pause_reasons: list[str]


def validate_definition(value):
    return ValidatedDefinition.model_validate(value)


def definition_view(row):
    return dict(id=row.id, department_id=row.department_id, code=row.code, name=row.name,
                definition=row.draft, revision=row.revision, published_version=row.published_version)


async def list_definitions(db, actor, *, available=False,scene=None):
    actor = await builtin_actor(db, actor)
    if scene not in {None,'leave','reimbursement'}: raise invalid('未知业务场景')
    selected=scene or ('leave' if available else None)
    require_permission(actor, selected if available else 'workflow', 'read')
    if not available and not department_permission(actor, 'workflow', 'read'):
        from .oa_access_service import denied
        raise denied()
    departments = actor.depts if available else await management_departments(db, actor, 'workflow', 'read')
    rows = (await db.scalars(select(OAWorkflowDefinition).where(OAWorkflowDefinition.tenant_id == actor.tenant_id,
        OAWorkflowDefinition.department_id.in_(departments)).order_by(OAWorkflowDefinition.name))).all()
    result = []
    for row in rows:
        if selected and row.scene!=selected: continue
        if not available:
            result.append(definition_view(row))
        elif row.published_version:
            version = await db.scalar(select(OAWorkflowVersion).where(OAWorkflowVersion.tenant_id==actor.tenant_id,
                OAWorkflowVersion.definition_id==row.id,OAWorkflowVersion.version==row.published_version))
            result.append(dict(id=row.id,name=row.name,published_version=row.published_version,form=version.package['form']))
    return result


async def workbench_options(db, actor, *, resource='workflow', action='read'):
    actor = await builtin_actor(db, actor)
    if resource not in {'workflow', 'leave_balance', 'workflow_admin', 'ticket_admin'} or action not in {'read', 'write'}:
        from .oa_access_service import denied
        raise denied()
    department_ids = await management_departments(db, actor, resource, action)
    departments = (await db.scalars(select(OADepartment).where(OADepartment.tenant_id==actor.tenant_id,
        OADepartment.id.in_(department_ids)).order_by(OADepartment.name))).all()
    users = (await db.scalars(select(OAUser).join(OAMembership,
        (OAMembership.tenant_id==OAUser.tenant_id)&(OAMembership.user_id==OAUser.id)).where(
        OAUser.tenant_id==actor.tenant_id,OAMembership.department_id.in_(department_ids),OAUser.status=='active')
        .order_by(OAUser.display_name, OAUser.id))).unique().all()
    roles = (await db.scalars(select(OARole).where(OARole.tenant_id==actor.tenant_id))).all()
    return dict(departments=[dict(id=d.id,name=d.name) for d in departments],
        users=[dict(id=u.id,name=u.display_name) for u in users],roles=[dict(id=r.id,name=r.name) for r in roles])


async def save_definition(db, actor, payload, definition_id=None):
    actor = await builtin_actor(db, actor)
    target_id = definition_id or str(uuid5(NAMESPACE_URL, 'oa:workflow:' + actor.tenant_id + ':' + payload.operation_id))
    target = OAAccessTarget(actor.tenant_id, department_id=payload.department_id)
    async def save(operation):
        if definition_id:
            row = await tenant_row(db, OAWorkflowDefinition, actor, definition_id, lock=True)
            await authorize_oa(db, actor, 'workflow', 'write', target=OAAccessTarget(actor.tenant_id, department_id=row.department_id))
            if row.revision != payload.expected_revision:
                raise revision_conflict()
            if row.department_id != payload.department_id or row.code != payload.code or row.scene!=payload.definition.scene:
                raise invalid('流程所属部门、编码与业务场景不可更改')
            row.name, row.draft = payload.name, payload.definition.model_dump(mode='json')
            row.revision += 1
        else:
            if await db.scalar(select(OAWorkflowDefinition.id).where(OAWorkflowDefinition.tenant_id == actor.tenant_id,
                OAWorkflowDefinition.department_id == payload.department_id, OAWorkflowDefinition.code == payload.code)):
                raise invalid('部门内流程编码已存在')
            row = OAWorkflowDefinition(id=target_id, tenant_id=actor.tenant_id, department_id=payload.department_id,
                code=payload.code, name=payload.name,scene=payload.definition.scene,draft=payload.definition.model_dump(mode='json'))
            db.add(row)
        await db.flush()
        return CommandOutcome(result=definition_view(row))
    result = await run_command(db, actor, OACommand(kind='workflow.save', target_id=target_id, target_version='draft',
        operation_id=payload.operation_id, payload=payload.model_dump(mode='json'), resource='workflow', target=target), save)
    return result.result


async def publish_definition(db, actor, definition_id, payload):
    actor = await builtin_actor(db, actor)
    row = await tenant_row(db, OAWorkflowDefinition, actor, definition_id)
    async def publish(operation):
        row = await tenant_row(db, OAWorkflowDefinition, actor, definition_id, lock=True)
        if row.revision != payload.expected_revision:
            raise revision_conflict()
        package = validate_definition(row.draft).model_dump(mode='json')
        if package['scene']!=row.scene: raise invalid('流程场景与发布内容不一致')
        previous = await db.scalar(select(OAWorkflowVersion).where(OAWorkflowVersion.tenant_id == actor.tenant_id,
            OAWorkflowVersion.definition_id == row.id, OAWorkflowVersion.version == row.published_version))
        form_hash, rule_hash = canonical_hash(package['form']), canonical_hash(package['rules'])
        version = OAWorkflowVersion(tenant_id=actor.tenant_id, definition_id=row.id, version=row.published_version + 1,
            form_version=previous.form_version + int(form_hash != previous.form_hash) if previous else 1,
            rule_version=previous.rule_version + int(rule_hash != previous.rule_hash) if previous else 1,
            package=package, workflow_hash=canonical_hash(package), form_hash=form_hash, rule_hash=rule_hash,
            published_by=actor.user_id)
        db.add(version)
        row.published_version, row.revision = version.version, row.revision + 1
        await db.flush()
        result = PublishedWorkflowView.model_validate(version, from_attributes=True).model_dump()
        result['revision'] = row.revision
        return CommandOutcome(result=result, recipients=[actor.user_id])
    return await run_command(db, actor, OACommand(kind='workflow.publish', target_id=row.id, target_version='publish',
        operation_id=payload.operation_id, payload=payload.model_dump(mode='json'), resource='workflow',
        target=OAAccessTarget(actor.tenant_id, department_id=row.department_id)), publish)


async def current_version(db, actor, definition_id,*,scene='leave'):
    actor = await builtin_actor(db, actor)
    if scene not in {'leave','reimbursement'}: raise invalid('未知业务场景')
    require_permission(actor, scene, 'read')
    row = await tenant_row(db, OAWorkflowDefinition, actor, definition_id)
    if row.scene!=scene: raise invalid('流程不属于当前业务场景')
    if row.department_id not in actor.depts:
        from .oa_access_service import denied
        raise denied()
    version = await db.scalar(select(OAWorkflowVersion).where(OAWorkflowVersion.tenant_id == actor.tenant_id,
        OAWorkflowVersion.definition_id == row.id, OAWorkflowVersion.version == row.published_version))
    if version is None:
        raise invalid('流程尚未发布')
    return version


async def selector_users(db, tenant, applicant_id, selector):
    membership = await db.get(OAMembership, (tenant, applicant_id), populate_existing=True)
    if selector.kind == 'users':
        return selector.user_ids
    if selector.kind == 'manager':
        cursor = applicant_id
        seen = {cursor}
        for _ in range(selector.levels):
            link = await db.get(OAMembership, (tenant, cursor), populate_existing=True)
            cursor = link.manager_id if link else None
            if not cursor or cursor in seen:
                return []
            seen.add(cursor)
        return [cursor]
    if not membership:
        return []
    role = await db.scalar(select(OARole).where(OARole.id == selector.role_id, OARole.tenant_id == tenant))
    if role is None:
        return []
    return list((await db.scalars(select(OAMembership.user_id).join(OAUserRole,
        (OAUserRole.user_id == OAMembership.user_id) & (OAUserRole.tenant_id == OAMembership.tenant_id)).where(
            OAMembership.tenant_id == tenant, OAMembership.department_id == membership.department_id,
            OAUserRole.role_id == selector.role_id).order_by(OAMembership.user_id))).all())


async def eligible_user(db, tenant, user_id, applicant_id, *, approval=True):
    user = await db.scalar(select(OAUser).where(OAUser.tenant_id == tenant, OAUser.id == user_id,
                                               OAUser.status == 'active').execution_options(populate_existing=True))
    if user is None or approval and user_id == applicant_id:
        return None
    fresh = await current_identity(db, user)
    from .oa_access_service import OAAccessTarget
    try:
        await authorize_oa(db, fresh, 'approval', 'read', target=OAAccessTarget(tenant, owner_id=user_id))
        if approval:
            require_permission(fresh, 'approval', 'write')
        membership = await db.get(OAMembership, (tenant, user_id), populate_existing=True)
        if not membership or not await db.scalar(select(OADepartment.id).where(
            OADepartment.tenant_id==tenant,OADepartment.id==membership.department_id,OADepartment.enabled.is_(True))):
            return None
        if membership and membership.position_id:
            position = await db.get(OAPosition, membership.position_id, populate_existing=True)
            if not position or not position.enabled:
                return None
        return fresh
    except Exception as exc:
        from ..core.errors import AppException
        if isinstance(exc, AppException):
            return None
        raise


async def resolve_route(db, actor, version, form):
    actor = await builtin_actor(db, actor)
    if version.tenant_id != actor.tenant_id:
        from .oa_access_service import denied
        raise denied()
    definition = validate_definition(version.package)
    from ..schemas.oa_reimbursement import ReimbursementFields
    from ..schemas.oa_leave import NormalizedLeaveFields
    if definition.scene=='leave':
        if not isinstance(form,NormalizedLeaveFields) or form.leave_type not in definition.form.leave_types or len(form.reason)>definition.form.reason_max_length:
            raise invalid('字段不符合已发布请假表单')
        values=form.model_dump()|{'days':form.days}
    else:
        if not isinstance(form,ReimbursementFields) or form.category not in definition.form.categories or len(form.purpose)>definition.form.purpose_max_length:
            raise invalid('字段不符合已发布报销表单')
        values=form.model_dump()|{'amount':form.amount_minor}
    by_id = {node.id: node for node in definition.nodes}
    nodes, reasons, cursor = [], [], definition.entry_id
    while True:
        node = by_id[cursor]
        if node.kind == 'end':
            break
        if node.kind == 'branch':
            cursor = next((case.next_id for case in node.cases if evaluate_condition(case.field, case.op, case.value, values)), node.default_next_id)
            continue
        users = list(dict.fromkeys(await selector_users(db, actor.tenant_id, actor.user_id, node.selector)))
        seats = []
        if not users or node.kind == 'approval' and node.mode == 'single' and len(users) != 1:
            reasons.append('审批人员为空或单签人数不符合要求')
        for user_id in users:
            eligible = await eligible_user(db, actor.tenant_id, user_id, actor.user_id, approval=node.kind == 'approval')
            member = await db.get(OAMembership, (actor.tenant_id, user_id), populate_existing=True)
            if not eligible:
                reasons.append('处理人已失效、缺少权限或存在自审')
            seats.append(dict(user_id=user_id, valid=bool(eligible), eligibility=dict(selector=node.selector.model_dump(mode='json'),
                department_id=member.department_id if member else None, position_id=member.position_id if member else None)))
        nodes.append(dict(key=node.id, kind=node.kind, mode=node.mode if node.kind == 'approval' else None,
                          seats=seats, timeout_hours=definition.rules.timeout_hours))
        cursor = node.next_id
    return RoutePlan(nodes=nodes, pause_reasons=list(dict.fromkeys(reasons)))


async def activate_next(db,instance,subject):
    from .oa_approval_service import seat_eligible
    nodes = (await db.scalars(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id==instance.tenant_id,
        OAWorkflowNode.instance_id==instance.id).order_by(OAWorkflowNode.ordinal).with_for_update())).all()
    recipients = []
    for node in nodes:
        if node.state=='ACTIVE': return recipients
        if node.state!='WAITING': continue
        seats = (await db.scalars(select(OAWorkflowSeat).where(OAWorkflowSeat.tenant_id==instance.tenant_id,
            OAWorkflowSeat.node_id==node.id).order_by(OAWorkflowSeat.id).with_for_update())).all()
        if not seats or any([not await seat_eligible(db,subject,node,seat) for seat in seats]):
            instance.state='PAUSED'
            instance.pause_reason='固定路线人员资格已变化，请由管理员核对并恢复'
            return recipients
        recipients.extend(seat.effective_user_id for seat in seats if seat.effective_user_id)
        if node.kind=='cc':
            node.state='DONE'
            for seat in seats: seat.state,seat.revision='CC',seat.revision+1
            continue
        node.state='ACTIVE'
        timeout = instance.route_snapshot[node.ordinal]['timeout_hours']
        node.due_at=datetime.now(timezone.utc)+timedelta(hours=timeout)
        break
    await db.flush()
    return recipients
