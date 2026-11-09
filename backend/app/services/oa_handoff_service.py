"""Explicit departmental seat administration, without permanent delegation."""
from datetime import datetime,timedelta,timezone

from sqlalchemy import select
from ..models.identity import OAUser,OAMembership
from ..models.oa_workflow import OAWorkflowInstance,OAWorkflowNode,OAWorkflowSeat
from .oa_access_service import (builtin_actor,authorize_oa,OAAccessTarget,tenant_row,user_department,
    invalid,revision_conflict,denied,management_departments)
from .oa_command_service import OACommand,CommandOutcome,run_command
from .oa_workflow_subject import resolve_subject
from . import oa_approval_service as approvals,oa_leave_service as leaves,oa_workflow_service as workflows


async def admin_target(db,actor,leave,action):
    target=OAAccessTarget(actor.tenant_id,leave.applicant_id,await user_department(db,actor.tenant_id,leave.applicant_id))
    await authorize_oa(db,actor,'workflow_admin',action,target=target)
    return target


async def replace_seat(db,leave,node,seats,seat,user_id):
    if node.state not in {'ACTIVE','WAITING'} or seat.state!='PENDING': raise invalid('已完成的席位不能转交')
    if user_id==seat.effective_user_id: raise invalid('接收人须与当前办理人不同')
    if any(other.id!=seat.id and other.effective_user_id==user_id for other in seats): raise invalid('接收人已占该节点其他席位')
    if not await workflows.eligible_user(db,leave.tenant_id,user_id,leave.applicant_id,approval=node.kind=='approval'):
        raise invalid('接收人未启用、缺少权限或存在自审')
    department=await user_department(db,leave.tenant_id,user_id)
    current_department=await user_department(db,leave.tenant_id,leave.applicant_id)
    selector=seat.eligibility.get('selector',{})
    if department!=current_department and not (selector.get('kind')=='users' and user_id in selector.get('user_ids',[])):
        raise denied()
    before=seat.effective_user_id
    seat.effective_user_id,seat.substituted,seat.revision=user_id,True,seat.revision+1
    node.revision+=1
    return dict(seat_id=seat.id,node_id=node.id,original_user_id=seat.original_user_id,before=before,after=user_id)


async def remaining_seats(db,actor,user_id,department_id):
    rows=(await db.scalars(select(OAWorkflowSeat)
        .join(OAWorkflowNode,(OAWorkflowNode.id==OAWorkflowSeat.node_id)&(OAWorkflowNode.tenant_id==OAWorkflowSeat.tenant_id))
        .join(OAWorkflowInstance,(OAWorkflowInstance.id==OAWorkflowNode.instance_id)&(OAWorkflowInstance.tenant_id==OAWorkflowNode.tenant_id))
        .where(OAWorkflowSeat.tenant_id==actor.tenant_id,OAWorkflowSeat.effective_user_id==user_id,
            OAWorkflowSeat.state=='PENDING',OAWorkflowNode.state.in_(['ACTIVE','WAITING']),
            OAWorkflowInstance.state.in_(['IN_REVIEW','PAUSED'])))).all()
    count=0
    for seat in rows:
        row,version,instance,_=await approvals.records(db,actor,seat.node_id)
        if row.submission_version==version.version and row.state in {'IN_REVIEW','PAUSED'} and not row.archived_at:
            if await user_department(db,actor.tenant_id,row.applicant_id)==department_id: count+=1
    return count


async def transfer(db,actor,seat_id,payload):
    actor=await builtin_actor(db,actor)
    seat=await tenant_row(db,OAWorkflowSeat,actor,seat_id)
    leave,_,_,_=await approvals.records(db,actor,seat.node_id)
    target=await admin_target(db,actor,leave,'write')
    async def perform(operation):
        row,version,instance,node=await approvals.records(db,actor,seat.node_id,lock=True)
        await admin_target(db,actor,row,'write')
        if row.submission_version!=version.version or row.state not in {'IN_REVIEW','PAUSED'} or row.archived_at:
            raise invalid('当前申请已结束，不能转交')
        if node.revision!=payload.expected_revision: raise revision_conflict()
        seats=await approvals.seats_for(db,node,lock=True)
        current=next(s for s in seats if s.id==seat_id)
        if current.substituted: raise invalid('不允许链式转交，请由管理员暂停核对后显式恢复')
        change=await replace_seat(db,row,node,seats,current,payload.target_user_id)
        instance.route_revision+=1
        instance.revision+=1
        row.revision+=1
        await db.flush()
        remaining=await remaining_seats(db,actor,change['before'],target.department_id)
        recipients=[payload.target_user_id] if node.state=='ACTIVE' and instance.state=='IN_REVIEW' else []
        return CommandOutcome(result=dict(seat_id=seat_id,revision=node.revision,route_revision=instance.route_revision,
            remaining_m2_seats=remaining,m2_handoff_complete=remaining==0,handoff_scope=dict(department_id=target.department_id)),
            recipients=recipients,recipient_access={uid:('approval',OAAccessTarget(actor.tenant_id,uid)) for uid in recipients},
            detail=dict(reason=payload.reason,route_revision=instance.route_revision,**change))
    return await run_command(db,actor,OACommand(kind='workflow.transfer',target_id=seat_id,target_version=str(payload.expected_revision),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='workflow_admin',target=target,
        applicant_id=leave.applicant_id),perform)


async def instance_records(db,actor,instance_id,*,lock=False):
    instance=await tenant_row(db,OAWorkflowInstance,actor,instance_id)
    subject=await resolve_subject(db,actor,instance,lock=lock)
    leave,version=subject.row,subject.version
    if lock: instance=await tenant_row(db,OAWorkflowInstance,actor,instance.id,lock=True)
    return leave,version,instance


async def resume(db,actor,instance_id,payload):
    actor=await builtin_actor(db,actor)
    leave,_,_=await instance_records(db,actor,instance_id)
    target=await admin_target(db,actor,leave,'write')
    async def perform(operation):
        row,version,instance=await instance_records(db,actor,instance_id,lock=True)
        await admin_target(db,actor,row,'write')
        if instance.revision!=payload.expected_revision: raise revision_conflict()
        if instance.state!='PAUSED' or row.state!='PAUSED' or row.submission_version!=version.version or row.archived_at:
            raise invalid('仅当前轮次暂停的路线可以恢复')
        if not payload.reason.strip(): raise invalid('请填写恢复理由')
        nodes=(await db.scalars(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id==actor.tenant_id,
            OAWorkflowNode.instance_id==instance_id).order_by(OAWorkflowNode.ordinal).with_for_update())).all()
        mapping={item.seat_id:item.target_user_id for item in payload.replacements}
        changes=[]
        for node in nodes:
            seats=await approvals.seats_for(db,node,lock=True)
            for seat in seats:
                if seat.id in mapping:
                    changes.append(await replace_seat(db,row,node,seats,seat,mapping.pop(seat.id)))
            if node.state in {'ACTIVE','WAITING'}:
                for seat in seats:
                    if seat.state=='PENDING' and not await approvals.seat_eligible(db,row,node,seat):
                        raise invalid('固定路线仍有未修正的失效人员')
        if mapping: raise invalid('替换席位不属于当前路线')
        from .oa_workflow_scheduler import reconciliation_issues
        if await reconciliation_issues(db,row,ignore_operation_id=operation.id): raise invalid('对账异常尚未处理，不能恢复')
        instance.state=row.state='IN_REVIEW'
        instance.pause_reason=None
        instance.route_revision+=1
        instance.revision+=1
        row.revision+=1
        for node in nodes:
            if node.state=='ACTIVE':
                node.due_at=datetime.now(timezone.utc)+timedelta(hours=instance.route_snapshot[node.ordinal]['timeout_hours'])
                node.revision+=1
        recipients=await workflows.activate_next(db,instance,row)
        for node in nodes:
            if node.state=='ACTIVE':
                recipients.extend(s.effective_user_id for s in await approvals.seats_for(db,node) if s.state=='PENDING')
        await db.flush()
        return CommandOutcome(result=dict(instance_id=instance_id,state=row.state,revision=instance.revision,route_revision=instance.route_revision),
            recipients=recipients,recipient_access={uid:('approval',OAAccessTarget(actor.tenant_id,uid)) for uid in recipients},
            detail=dict(reason=payload.reason,changes=changes,route_revision=instance.route_revision))
    return await run_command(db,actor,OACommand(kind='workflow.resume',target_id=instance_id,target_version=str(payload.expected_revision),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='workflow_admin',target=target,
        applicant_id=leave.applicant_id),perform)


async def list_instances(db,actor):
    actor=await builtin_actor(db,actor)
    departments=await management_departments(db,actor,'workflow_admin','read')
    instances=(await db.scalars(select(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id==actor.tenant_id)
        .order_by(OAWorkflowInstance.created_at.desc()))).all()
    result=[]
    for instance in instances:
        subject=await resolve_subject(db,actor,instance)
        leave,version=subject.row,subject.version
        if leave.submission_version!=version.version or await user_department(db,actor.tenant_id,leave.applicant_id) not in departments: continue
        await admin_target(db,actor,leave,'read')
        nodes=(await db.scalars(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id==actor.tenant_id,
            OAWorkflowNode.instance_id==instance.id).order_by(OAWorkflowNode.ordinal))).all()
        item=dict(instance_id=instance.id,scene=instance.scene,object_id=leave.id,
            leave_id=leave.id if instance.scene=='leave' else None,
            reimbursement_id=leave.id if instance.scene=='reimbursement' else None,business_no=leave.business_no,applicant_id=leave.applicant_id,
            state=instance.state,pause_reason=instance.pause_reason,revision=instance.revision,route_revision=instance.route_revision,nodes=[])
        for node in nodes:
            seats=await approvals.seats_for(db,node)
            names=dict((await db.execute(select(OAUser.id,OAUser.display_name).where(
                OAUser.tenant_id==actor.tenant_id,OAUser.id.in_([s.effective_user_id for s in seats])))).all())
            item['nodes'].append(dict(id=node.id,ordinal=node.ordinal,kind=node.kind,mode=node.mode,state=node.state,
                revision=node.revision,due_at=node.due_at.isoformat() if node.due_at else None,seats=[dict(id=s.id,
                    original_user_id=s.original_user_id,effective_user_id=s.effective_user_id,
                    effective_user_name=names.get(s.effective_user_id,'待指定办理人'),state=s.state,
                    substituted=s.substituted,escalated=s.escalated) for s in seats]))
        result.append(item)
    return result


async def candidates(db,actor,seat_id):
    actor=await builtin_actor(db,actor)
    seat=await tenant_row(db,OAWorkflowSeat,actor,seat_id)
    leave,_,_,node=await approvals.records(db,actor,seat.node_id)
    target=await admin_target(db,actor,leave,'read')
    users=(await db.scalars(select(OAUser).where(OAUser.tenant_id==actor.tenant_id,OAUser.status=='active'))).all()
    seats=await approvals.seats_for(db,node)
    selector=seat.eligibility.get('selector',{})
    result=[]
    for user in users:
        department=await user_department(db,actor.tenant_id,user.id)
        if department!=target.department_id and not (selector.get('kind')=='users' and user.id in selector.get('user_ids',[])): continue
        if any(s.id!=seat.id and s.effective_user_id==user.id for s in seats): continue
        if await workflows.eligible_user(db,actor.tenant_id,user.id,leave.applicant_id,approval=node.kind=='approval'):
            result.append(dict(id=user.id,name=user.display_name))
    return result
