"""Lifecycle handoff inventory with domain authority and immutable original owners."""
from sqlalchemy import select, or_

from ..core.errors import AppException
from ..models.identity import OAUser, OAMembership, OADepartment, OAPosition
from ..models.oa_workflow import OAWorkflowSeat, OAWorkflowNode, OAWorkflowInstance
from ..models.oa_ticket import OATicket, OATicketAssignmentRule
from ..models.work_task import WorkTask
from ..models.work_task_event import WorkTaskEvent
from ..models.audit_event import AuditEvent
from ..schemas.organization import UserUpdate
from ..schemas.oa_workflow import SeatHandoffCommand
from ..schemas.oa_ticket import TicketHandleCommand, TicketRuleSave
from . import organization_service as org, idempotency_service
from . import oa_handoff_service as workflows, oa_approval_service as approvals, oa_ticket_service as tickets
from .oa_access_service import (OAAccessTarget, authorize_oa, user_department, department_permission,
    denied, invalid, revision_conflict)
from .identity_service import current_identity

KIND_NAMES = dict(workflow='审批席位', ticket='待办工单', work_task='业务任务',
    ticket_rule='工单分派规则', reporting_line='直属下级')


async def pending(db, actor, user_id):
    """Unfiltered inventory is also used for signoff; hidden work still blocks completion."""
    result = []
    seats = (await db.scalars(select(OAWorkflowSeat)
        .join(OAWorkflowNode, (OAWorkflowSeat.node_id == OAWorkflowNode.id) & (OAWorkflowSeat.tenant_id == OAWorkflowNode.tenant_id))
        .join(OAWorkflowInstance, (OAWorkflowNode.instance_id == OAWorkflowInstance.id) & (OAWorkflowNode.tenant_id == OAWorkflowInstance.tenant_id))
        .where(OAWorkflowSeat.tenant_id == actor.tenant_id, OAWorkflowSeat.effective_user_id == user_id,
            OAWorkflowSeat.state == 'PENDING', OAWorkflowNode.state.in_(['ACTIVE','WAITING']),
            OAWorkflowInstance.state.in_(['IN_REVIEW','PAUSED'])))).all()
    for seat in seats:
        subject, version, instance, node = await approvals.records(db, actor, seat.node_id)
        if subject.submission_version == version.version and subject.state in {'IN_REVIEW','PAUSED'} and not subject.archived_at:
            result.append(dict(kind='workflow', id=seat.id, revision=node.revision, title=subject.business_no,
                row=seat, subject=subject, node=node, link='/oa/administration',
                blocked_reason='已转交过的席位需在流程管理中暂停核对并恢复' if seat.substituted else ''))
    for row in (await db.scalars(select(OATicket).where(OATicket.tenant_id == actor.tenant_id,
            OATicket.assignee_id == user_id, OATicket.state.in_(['OPEN','IN_PROGRESS'])))).all():
        result.append(dict(kind='ticket', id=row.id, revision=row.revision, title=row.business_no, row=row, link='/oa/tickets'))
    for row in (await db.scalars(select(WorkTask).where(WorkTask.tenant_id == actor.tenant_id,
            WorkTask.status.in_(['OPEN','IN_PROGRESS']), or_(WorkTask.assignee_id == user_id,
                (WorkTask.creator_id == user_id) & WorkTask.handoff_department_id.is_(None))))).all():
        result.append(dict(kind='work_task', id=row.task_id, revision=row.version, title=row.title, row=row, link='/work-tasks'))
    rules = (await db.scalars(select(OATicketAssignmentRule).where(OATicketAssignmentRule.tenant_id == actor.tenant_id)
        .order_by(OATicketAssignmentRule.version.desc()))).all()
    latest = {}
    for row in rules:
        latest.setdefault((row.department_id, row.code), row)
    for row in latest.values():
        if row.enabled and row.assignee_id == user_id:
            result.append(dict(kind='ticket_rule', id=row.id, revision=row.version, title=row.queue, row=row, link='/oa/ticket-rules'))
    for row in (await db.scalars(select(OAMembership).where(OAMembership.tenant_id == actor.tenant_id,
            OAMembership.manager_id == user_id))).all():
        user = await db.get(OAUser, row.user_id)
        result.append(dict(kind='reporting_line', id=row.user_id, revision=user.authorization_version,
            title=user.display_name, row=user, link='/organization'))
    return result


async def task_department(db, actor, row):
    return row.handoff_department_id or await user_department(db, actor.tenant_id, row.creator_id)


async def task_authority(db, actor, row, action):
    department = await task_department(db, actor, row)
    if not department or department not in actor.depts or not department_permission(actor, 'work_task', action):
        raise denied()
    await org._target(db, OADepartment, department, actor.tenant_id, True)
    return department


async def domain_access(db, actor, item, action):
    row, kind = item['row'], item['kind']
    if kind == 'workflow':
        await workflows.admin_target(db, actor, item['subject'], action)
    elif kind == 'ticket':
        await tickets.access(db, actor, row.id, action=action, resource='ticket_handle')
        await authorize_oa(db, actor, 'ticket_admin', action,
            target=OAAccessTarget(actor.tenant_id, department_id=row.department_id))
    elif kind == 'ticket_rule':
        await authorize_oa(db, actor, 'ticket_admin', action,
            target=OAAccessTarget(actor.tenant_id, department_id=row.department_id))
    elif kind == 'work_task':
        await task_authority(db, actor, row, action)


async def inventory(db, actor, user_id):
    actor = await org._actor(db, actor, 'read')
    user = await org._target(db, OAUser, user_id, actor.tenant_id)
    counts = {kind: 0 for kind in KIND_NAMES}
    items, restricted = [], 0
    for item in await pending(db, actor, user_id):
        counts[item['kind']] += 1
        try:
            await domain_access(db, actor, item, 'read')
        except AppException as error:
            if error.http_status not in {403,422}:
                raise
            restricted += 1
            continue
        can_transfer = not item.get('blocked_reason')
        try:
            await org._actor(db, actor)
            await domain_access(db, actor, item, 'write')
        except AppException as error:
            if error.http_status not in {403,422}:
                raise
            can_transfer = False
        items.append({k: item[k] for k in ('kind','id','revision','title','link')} | dict(
            kind_name=KIND_NAMES[item['kind']], can_transfer=can_transfer, blocked_reason=item.get('blocked_reason','')))
    history = (await db.scalars(select(AuditEvent).where(AuditEvent.target_id == user_id,
        AuditEvent.actor_id.in_(select(OAUser.id).where(OAUser.tenant_id == actor.tenant_id)),
        AuditEvent.action.in_(['organization.user_create','organization.member_change',
            'organization.handoff_transfer','organization.handoff_complete']))
        .order_by(AuditEvent.id.desc()).limit(30))).all()
    labels = {'organization.user_create':'入职建号', 'organization.member_change':'成员调整',
        'organization.handoff_transfer':'业务交接', 'organization.handoff_complete':'交接完成'}
    return dict(member=await org._user_view(db, user), counts=counts, total=sum(counts.values()), items=items,
        restricted_count=restricted, history=[dict(id=h.id, action=labels[h.action],
            reason=(h.output_summary or {}).get('reason',''), created_at=h.created_at.isoformat()) for h in history])


async def find_item(db, actor, user_id, kind, item_id, action='write'):
    await org._target(db, OAUser, user_id, actor.tenant_id)
    item = next((i for i in await pending(db, actor, user_id) if i['kind'] == kind and i['id'] == item_id), None)
    if item is None:
        raise revision_conflict()
    await domain_access(db, actor, item, action)
    if item.get('blocked_reason'):
        raise invalid(item['blocked_reason'])
    return item


async def manager_allowed(db, tenant, report_id, manager_id):
    seen = {report_id}
    while manager_id:
        if manager_id in seen:
            return False
        seen.add(manager_id)
        membership = await db.get(OAMembership, (tenant, manager_id))
        manager_id = membership.manager_id if membership else None
    return True


async def candidates_for(db, actor, user_id, item):
    kind, row = item['kind'], item['row']
    if kind == 'workflow':
        return [u for u in await workflows.candidates(db, actor, row.id) if u['id'] != user_id]
    users = (await db.scalars(select(OAUser).where(OAUser.tenant_id == actor.tenant_id,
        OAUser.status == 'active', OAUser.id != user_id).order_by(OAUser.display_name, OAUser.id))).all()
    result = []
    for user in users:
        membership = await db.get(OAMembership, (actor.tenant_id, user.id))
        if not membership:
            continue
        dept = await db.get(OADepartment, membership.department_id)
        position = await db.get(OAPosition, membership.position_id) if membership.position_id else None
        if not dept or not dept.enabled or position and not position.enabled:
            continue
        if kind in {'ticket','ticket_rule'}:
            if not await tickets.eligible_handler(db, actor.tenant_id, user.id, row.department_id):
                continue
        elif kind == 'work_task':
            if membership.department_id != await task_department(db, actor, row):
                continue
            candidate = await current_identity(db, user)
            if not all(any(p['resource'] == 'work_task' and p['action'] == a for p in candidate.data_scope['permissions']) for a in ('read','write')):
                continue
        elif kind == 'reporting_line' and not await manager_allowed(db, actor.tenant_id, row.id, user.id):
            continue
        result.append(dict(id=user.id, name=user.display_name))
    return result


async def candidates(db, actor, user_id, kind, item_id):
    actor = await org._actor(db, actor)
    item = await find_item(db, actor, user_id, kind, item_id)
    return await candidates_for(db, actor, user_id, item)


async def transfer(db, actor, user_id, payload):
    actor = await org._manage(db, actor)
    user = await org._target(db, OAUser, user_id, actor.tenant_id)
    async with db.begin_nested():
        command, fresh = await org.member_command(db, actor, user_id, 'handoff_transfer', payload)
        if not fresh:
            result = command.result
        else:
            if user.authorization_version != payload.expected_version:
                raise revision_conflict()
            item = await find_item(db, actor, user_id, payload.kind, payload.item_id)
            if item['revision'] != payload.expected_revision:
                raise revision_conflict()
            if payload.target_user_id not in {u['id'] for u in await candidates_for(db, actor, user_id, item)}:
                raise invalid('接收人资格已变化，请刷新候选成员')
            row = item['row']
            if payload.kind == 'workflow':
                await workflows.transfer(db, actor, row.id, SeatHandoffCommand(operation_id=payload.operation_id,
                    expected_revision=payload.expected_revision, target_user_id=payload.target_user_id, reason=payload.reason))
            elif payload.kind == 'ticket':
                await tickets.handle(db, actor, row.id, TicketHandleCommand(operation_id=payload.operation_id,
                    expected_revision=payload.expected_revision, action='reassign', target_user_id=payload.target_user_id, note=payload.reason))
            elif payload.kind == 'ticket_rule':
                await tickets.save_rule(db, actor, TicketRuleSave(operation_id=payload.operation_id, department_id=row.department_id,
                    code=row.code, expected_version=row.version, category=row.category, impact=row.impact, queue=row.queue,
                    assignee_id=payload.target_user_id, priority=row.priority, enabled=True))
            elif payload.kind == 'reporting_line':
                before = await org._user_view(db, row)
                await org._update_user(db, actor, row, UserUpdate(**{k: before[k] for k in
                    ('display_name','status','department_id','position_id','role_ids')} | dict(manager_id=payload.target_user_id,
                        expected_version=payload.expected_revision)))
                org.lifecycle_event(db, actor, row.id, 'organization.member_change', reason=payload.reason,
                    before=before, after=await org._user_view(db, row))
            else:
                row = await db.scalar(select(WorkTask).where(WorkTask.id == row.id,
                    WorkTask.tenant_id == actor.tenant_id).with_for_update().execution_options(populate_existing=True))
                if row.version != payload.expected_revision or row.status not in {'OPEN','IN_PROGRESS'}:
                    raise revision_conflict()
                if not payload.risk_acknowledged:
                    raise invalid('请确认接收人可根据任务内容继续办理，原始材料访问权限不随交接扩大')
                before = dict(assignee_id=row.assignee_id, handoff_department_id=row.handoff_department_id)
                row.handoff_department_id = await task_department(db, actor, row)
                row.assignee_id = payload.target_user_id
                row.version += 1
                row.deadline_version += 1
                row.notification_scan_at = None
                db.add(WorkTaskEvent(task_id=row.id, actor_id=actor.user_id, action='handoff', version=row.version,
                    details=dict(before=before, assignee_id=row.assignee_id, creator_id=row.creator_id,
                        department_id=row.handoff_department_id, reason=payload.reason, risk_acknowledged=True)))
            await db.flush()
            org.lifecycle_event(db, actor, user_id, 'organization.handoff_transfer', reason=payload.reason.strip(),
                kind=payload.kind, item_id=payload.item_id, target_user_id=payload.target_user_id)
            result = dict(user_id=user_id, remaining=len(await pending(db, actor, user_id)))
            await idempotency_service.complete(db, command, result)
            if payload.kind == 'reporting_line' and row.id == actor.user_id:
                # Organization authority was checked under the tenant/member locks.
                db.info.get('identity_actors', {}).pop(actor.user_id, None)
    await db.commit()
    return result


async def complete(db, actor, user_id, payload):
    actor = await org._manage(db, actor)
    user = await org._target(db, OAUser, user_id, actor.tenant_id)
    async with db.begin_nested():
        command, fresh = await org.member_command(db, actor, user_id, 'handoff_complete', payload)
        if not fresh:
            result = command.result
        else:
            if user.authorization_version != payload.expected_version:
                raise revision_conflict()
            if not user.handoff_pending:
                raise invalid('该成员没有待确认的交接')
            if await pending(db, actor, user_id):
                raise invalid('仍有未交接事项，请完成全部交接后再确认')
            user.handoff_pending = False
            await org._bump(db, user)
            await db.flush()
            result = await org._user_view(db, user)
            org.lifecycle_event(db, actor, user_id, 'organization.handoff_complete', reason=payload.reason.strip())
            await idempotency_service.complete(db, command, result)
            if user_id == actor.user_id:
                db.info.get('identity_actors', {}).pop(actor.user_id, None)
    # Deliberate self-signoff changes only the handoff marker and its version.
    db.info.get('identity_actors', {}).pop(actor.user_id, None)
    await db.commit()
    return result
