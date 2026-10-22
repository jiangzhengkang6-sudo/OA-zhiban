"""Current-seat authorization and deterministic decisions for manual workflows."""
import asyncio

from sqlalchemy import select
from ..models.identity import OAMembership
from ..models.oa_workflow import OAWorkflowInstance, OAWorkflowNode, OAWorkflowSeat
from ..schemas.oa_workflow import Selector
from .oa_access_service import builtin_actor, authorize_oa, OAAccessTarget, tenant_row, denied, invalid, revision_conflict
from .oa_command_service import OACommand, CommandOutcome, run_command
from .oa_workflow_subject import resolve_subject, subject_scene
from . import oa_workflow_service as workflows, oa_leave_service as leaves, oa_balance_service as balances


async def records(db, actor, node_id, *, lock=False):
    node = await tenant_row(db,OAWorkflowNode,actor,node_id)
    instance = await tenant_row(db,OAWorkflowInstance,actor,node.instance_id)
    subject = await resolve_subject(db,actor,instance,lock=lock)
    leave,version = subject.row,subject.version
    if lock:
        instance = await tenant_row(db,OAWorkflowInstance,actor,instance.id,lock=True)
        node = await tenant_row(db,OAWorkflowNode,actor,node.id,lock=True)
    return leave,version,instance,node


async def seats_for(db, node, *, lock=False):
    query = select(OAWorkflowSeat).where(OAWorkflowSeat.tenant_id==node.tenant_id,
        OAWorkflowSeat.node_id==node.id).order_by(OAWorkflowSeat.id).execution_options(populate_existing=True)
    return list((await db.scalars(query.with_for_update() if lock else query)).all())


async def seat_eligible(db, leave, node, seat):
    user_id = seat.effective_user_id
    if not user_id or not await workflows.eligible_user(db,leave.tenant_id,user_id,leave.applicant_id,approval=node.kind=='approval'):
        return False
    membership = await db.get(OAMembership,(leave.tenant_id,user_id),populate_existing=True)
    fixed = seat.eligibility
    if seat.substituted:
        applicant = await db.get(OAMembership,(leave.tenant_id,leave.applicant_id),populate_existing=True)
        selector = fixed.get('selector',{})
        return bool(applicant and (membership.department_id==applicant.department_id or
            selector.get('kind')=='users' and user_id in selector.get('user_ids',[])))
    if membership.department_id!=fixed.get('department_id') or membership.position_id!=fixed.get('position_id'):
        return False
    selector = Selector.model_validate(fixed['selector'])
    return user_id in await workflows.selector_users(db,leave.tenant_id,leave.applicant_id,selector)


def active_round(leave,version,instance,node):
    return (not leave.archived_at and leave.submission_version==version.version and
        leave.state=='IN_REVIEW' and instance.state=='IN_REVIEW' and node.state=='ACTIVE')


async def node_access(db,actor,node_id,*,write=False,lock=False,allow_completed=False):
    actor = await builtin_actor(db,actor)
    await authorize_oa(db,actor,'approval','write' if write else 'read',target=OAAccessTarget(actor.tenant_id,actor.user_id))
    leave,version,instance,node = await records(db,actor,node_id,lock=lock)
    seats = await seats_for(db,node,lock=lock)
    seat = next((s for s in seats if s.effective_user_id==actor.user_id),None)
    if not seat or not await seat_eligible(db,leave,node,seat): raise denied()
    current = active_round(leave,version,instance,node) and node.kind=='approval' and seat.state=='PENDING'
    completed = allow_completed and seat.decided_by==actor.user_id and seat.state in {'APPROVED','REJECTED'}
    if not current and not completed: raise denied()
    return actor,leave,version,instance,node,seats,seat


def summary(leave,version,instance,node,seat):
    scene = subject_scene(leave)
    return dict(scene=scene,object_id=leave.id,leave_id=leave.id if scene=='leave' else None,
        reimbursement_id=leave.id if scene=='reimbursement' else None,business_no=leave.business_no,applicant_id=leave.applicant_id,
        submission_version=version.version,node_id=node.id,node_key=node.node_key,revision=node.revision,
        state=instance.state,seat_state=seat.state,decision_note=seat.decision_note,
        due_at=node.due_at.isoformat() if node.due_at else None)


async def list_items(db,actor,kind):
    if kind not in {'pending','done','cc'}: raise invalid('未知审批列表')
    actor = await builtin_actor(db,actor)
    await authorize_oa(db,actor,'approval','read',target=OAAccessTarget(actor.tenant_id,actor.user_id))
    seats = (await db.scalars(select(OAWorkflowSeat).where(OAWorkflowSeat.tenant_id==actor.tenant_id,
        OAWorkflowSeat.effective_user_id==actor.user_id).order_by(OAWorkflowSeat.created_at.desc()))).all()
    result = []
    for seat in seats:
        leave,version,instance,node = await records(db,actor,seat.node_id)
        if kind=='pending':
            if not active_round(leave,version,instance,node) or node.kind!='approval' or seat.state!='PENDING': continue
            if not await seat_eligible(db,leave,node,seat): continue
        elif kind=='done':
            if seat.decided_by!=actor.user_id or seat.state not in {'APPROVED','REJECTED'}: continue
        elif seat.state!='CC': continue
        result.append(summary(leave,version,instance,node,seat))
    return result


async def node_context(db,actor,node_id):
    _,leave,version,instance,node,seats,seat = await node_access(db,actor,node_id)
    result = summary(leave,version,instance,node,seat)
    result.update(fields=version.fields,attachments=version.attachments,allowed_actions=['approve','reject','return_for_correction'],
        mode=node.mode,approval_notes=await approval_notes(db,actor,instance.id))
    return result


async def approval_notes(db,actor,instance_id):
    from ..models.oa_workflow import OAWorkflowEvent
    node_ids = select(OAWorkflowNode.id).where(OAWorkflowNode.tenant_id==actor.tenant_id,OAWorkflowNode.instance_id==instance_id)
    events = (await db.scalars(select(OAWorkflowEvent).where(OAWorkflowEvent.tenant_id==actor.tenant_id,
        OAWorkflowEvent.action=='approval.decide',OAWorkflowEvent.target_id.in_(node_ids)).order_by(OAWorkflowEvent.created_at))).all()
    return [dict(actor_id=e.actor_id,note=e.detail['approval_note']) for e in events
        if e.detail.get('instance_id')==instance_id and e.detail.get('approval_note')]


async def cancel_remaining(db,instance):
    nodes = (await db.scalars(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id==instance.tenant_id,
        OAWorkflowNode.instance_id==instance.id).order_by(OAWorkflowNode.ordinal).with_for_update())).all()
    for node in nodes:
        if node.state in {'ACTIVE','WAITING'}:
            node.state,node.revision='CANCELLED',node.revision+1
        for seat in await seats_for(db,node,lock=True):
            if seat.state=='PENDING': seat.state,seat.revision='CANCELLED',seat.revision+1


async def decide(db,actor,node_id,payload):
    actor = await builtin_actor(db,actor)
    leave,_,_,_ = await records(db,actor,node_id)
    locked = []
    async def reauthorize():
        locked[:] = await node_access(db,actor,node_id,write=True,lock=True,allow_completed=True)
    async def perform(operation):
        _,row,version,instance,node,seats,seat = locked
        allowed={'leave_type','start_date','end_date','reason','attachment_ids'} if instance.scene=='leave' else {'purpose','expense_date','category','amount','currency','attachment_ids'}
        if set(payload.corrections)-allowed: raise invalid('修正字段不属于当前业务场景')
        if not active_round(row,version,instance,node) or seat.state!='PENDING': raise invalid('该节点已办理或不再有效')
        if node.revision!=payload.expected_revision: raise revision_conflict()
        from .oa_workflow_scheduler import reconciliation_issues
        if await reconciliation_issues(db,row,ignore_operation_id=operation.id):
            raise invalid('对账异常，请管理员核对后再办理')
        # Revalidate every unfinished seat; a changed fixed route needs explicit recovery.
        if any([not await seat_eligible(db,row,node,s) for s in seats if s.state=='PENDING']):
            raise invalid('节点人员资格已变化，请由管理员处理异常')
        seat.state = 'APPROVED' if payload.action=='approve' else 'REJECTED'
        seat.decided_by,seat.decision_note,seat.revision = actor.user_id,payload.note,seat.revision+1
        node.revision+=1
        row.revision+=1
        instance.revision+=1
        recipients = []
        if payload.action!='approve':
            node.state='DONE'
            row.state=instance.state='REJECTED'
            await cancel_remaining(db,instance)
            if instance.scene=='leave': await balances.settle(db,row,version,operation,'RELEASE')
        elif node.mode in {'single','any'} or all(s.state=='APPROVED' for s in seats):
            node.state='DONE'
            for other in seats:
                if other.state=='PENDING': other.state,other.revision='CANCELLED',other.revision+1
            recipients = await workflows.activate_next(db,instance,row)
            remaining = await db.scalar(select(OAWorkflowNode.id).where(OAWorkflowNode.tenant_id==actor.tenant_id,
                OAWorkflowNode.instance_id==instance.id,OAWorkflowNode.state.in_(['WAITING','ACTIVE'])))
            if instance.state=='PAUSED': row.state='PAUSED'
            elif not remaining:
                row.state=instance.state='APPROVED'
                if instance.scene=='leave': await balances.settle(db,row,version,operation,'CONSUME')
        if row.state in {'APPROVED','REJECTED','PAUSED'}: recipients.append(row.applicant_id)
        await db.flush()
        access = {uid:('approval',OAAccessTarget(actor.tenant_id,uid)) for uid in recipients}
        access[row.applicant_id]=(instance.scene,await leaves.target_for(db,actor,row))
        return CommandOutcome(result=dict(scene=instance.scene,object_id=row.id,
            leave_id=row.id if instance.scene=='leave' else None,
            reimbursement_id=row.id if instance.scene=='reimbursement' else None,
            node_id=node.id,state=row.state,revision=node.revision,object_revision=row.revision,
            leave_revision=row.revision if instance.scene=='leave' else None),recipients=recipients,recipient_access=access,
            detail=dict(instance_id=instance.id,action=payload.action,note=payload.note,reason_code=payload.reason_code,
                corrections=payload.corrections,
                approval_note=payload.approval_note,submission_version=version.version),
            changes=dict(before=dict(state='IN_REVIEW'),after=dict(state=row.state)))
    outcome = await run_command(db,actor,OACommand(kind='approval.decide',target_id=node_id,target_version=str(payload.expected_revision),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='approval',
        target=OAAccessTarget(actor.tenant_id,actor.user_id),applicant_id=leave.applicant_id,reauthorize=reauthorize),perform)
    outcome.current_revision=locked[4].revision
    outcome.allowed_actions=['approve','reject','return_for_correction'] if active_round(*locked[1:5]) and locked[6].state=='PENDING' else []
    return outcome


async def download(db,actor,node_id,attachment_id):
    from . import oa_attachment_service as attachments
    from .oa_workflow_subject import attachment_refs
    actor,leave,version,instance,_,_,_ = await node_access(db,actor,node_id)
    if attachment_id not in {item['id'] for item in version.attachments}: raise denied()
    row = (await attachment_refs(db,actor,leave,[attachment_id]))[0]
    if row.scan_status!='CLEAN': raise invalid('附件未通过安全扫描')
    try: content = await asyncio.to_thread(attachments.read_verified,row)
    except OSError: raise invalid('附件缺失或完整性校验失败') from None
    await node_access(db,actor,node_id)
    return row,content
