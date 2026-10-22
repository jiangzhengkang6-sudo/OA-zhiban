"""Database-backed manual workflow timers and read-only reconciliation."""
import logging
from datetime import datetime,timedelta,timezone
from uuid import uuid5,NAMESPACE_URL

from sqlalchemy import select
from ..core.errors import AppException
from ..models.identity import OAUser,OAMembership
from ..models.oa_leave import OALeaveBalance,OALeaveLedger
from ..models.oa_workflow import (OAWorkflowInstance,OAWorkflowNode,OAWorkflowSeat,OAWorkflowOperation,OAWorkflowEvent)
from ..schemas.oa_leave import NormalizedLeaveFields
from .identity_service import current_identity
from .oa_access_service import builtin_actor,OAAccessTarget,invalid
from .oa_command_service import OACommand,CommandOutcome,run_command
from .oa_workflow_subject import resolve_subject, subject_scene, subject_models
from . import oa_approval_service as approvals,oa_handoff_service as handoff,oa_workflow_service as workflows

logger=logging.getLogger('oa-agent')


async def reconciliation_issues(db,leave,*,ignore_operation_id=None):
    issues=[]
    scene=subject_scene(leave)
    _,version_model,object_key,association=subject_models(scene)
    balances=(await db.scalars(select(OALeaveBalance).where(OALeaveBalance.tenant_id==leave.tenant_id,
        OALeaveBalance.user_id==leave.applicant_id))).all() if scene=='leave' else []
    for balance in balances:
        ledger=(await db.scalars(select(OALeaveLedger).where(OALeaveLedger.tenant_id==leave.tenant_id,
            OALeaveLedger.balance_id==balance.id))).all()
        expected={key:sum(getattr(item,key+'_delta') for item in ledger) for key in ('total','used','reserved')}
        if any(getattr(balance,key)!=value for key,value in expected.items()):
            issues.append(dict(code='balance_ledger_mismatch',balance_id=balance.id))
        if any(any(item.before.get(key,0)+getattr(item,key+'_delta')!=item.after.get(key) for key in expected) for item in ledger):
            issues.append(dict(code='ledger_movement_mismatch',balance_id=balance.id))
    versions=(await db.scalars(select(version_model).where(version_model.tenant_id==leave.tenant_id,
        getattr(version_model,object_key)==leave.id))).all()
    target_ids=[leave.id]
    for version in versions:
        instances=(await db.scalars(select(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id==leave.tenant_id,
            OAWorkflowInstance.scene==scene,getattr(OAWorkflowInstance,association)==version.id))).all()
        if len(instances)!=1:
            issues.append(dict(code='instance_count_mismatch',submission_version=version.version))
            continue
        instance=instances[0]
        target_ids.append(instance.id)
        nodes=(await db.scalars(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id==leave.tenant_id,
            OAWorkflowNode.instance_id==instance.id))).all()
        target_ids.extend(n.id for n in nodes)
        seats=(await db.scalars(select(OAWorkflowSeat).where(OAWorkflowSeat.tenant_id==leave.tenant_id,
            OAWorkflowSeat.node_id.in_([n.id for n in nodes])))).all()
        target_ids.extend(s.id for s in seats)
        for node in nodes:
            if node.kind=='approval' and node.mode=='single' and sum(s.node_id==node.id for s in seats)!=1:
                issues.append(dict(code='single_seat_count_mismatch',node_id=node.id))
        active=[n for n in nodes if n.state=='ACTIVE']
        if instance.state=='IN_REVIEW' and len(active)!=1 or len(active)>1:
            issues.append(dict(code='active_node_mismatch',instance_id=instance.id))
        if any(n.kind=='approval' and not any(s.node_id==n.id and s.state=='PENDING' for s in seats) for n in active):
            issues.append(dict(code='active_seat_mismatch',instance_id=instance.id))
        if instance.state in {'APPROVED','REJECTED','CANCELLED'} and any(n.state in {'ACTIVE','WAITING'} for n in nodes):
            issues.append(dict(code='terminal_node_mismatch',instance_id=instance.id))
        if version.version==leave.submission_version and leave.state!=instance.state:
            issues.append(dict(code='instance_state_mismatch',instance_id=instance.id))
        if scene!='leave': continue
        ledger=(await db.scalars(select(OALeaveLedger).where(OALeaveLedger.tenant_id==leave.tenant_id,
            OALeaveLedger.leave_version_id==version.id))).all()
        form=NormalizedLeaveFields.model_validate(version.fields)
        for year,days in form.days_by_year.items():
            balance=next((b for b in balances if b.leave_type==form.leave_type and b.year==year),None)
            movements=[item for item in ledger if balance and item.balance_id==balance.id]
            reserve=[item for item in movements if item.kind=='RESERVE']
            consume=[item for item in movements if item.kind=='CONSUME']
            release=[item for item in movements if item.kind=='RELEASE']
            expected_final='CONSUME' if instance.state=='APPROVED' else 'RELEASE' if instance.state in {'REJECTED','CANCELLED'} else None
            valid=balance and len(reserve)==1 and reserve[0].reserved_delta==days
            if expected_final=='CONSUME': valid=valid and len(consume)==1 and not release and consume[0].used_delta==days and consume[0].reserved_delta==-days
            elif expected_final=='RELEASE': valid=valid and len(release)==1 and not consume and release[0].reserved_delta==-days
            else: valid=valid and not consume and not release
            if not valid: issues.append(dict(code='version_settlement_mismatch',submission_version=version.version,year=year))
    operations=(await db.scalars(select(OAWorkflowOperation).where(OAWorkflowOperation.tenant_id==leave.tenant_id,
        OAWorkflowOperation.target_id.in_(target_ids)))).all()
    events=(await db.scalars(select(OAWorkflowEvent.operation_id).where(OAWorkflowEvent.tenant_id==leave.tenant_id,
        OAWorkflowEvent.operation_id.in_([op.id for op in operations])))).all()
    for operation in operations:
        if operation.id!=ignore_operation_id and events.count(operation.id)!=1:
            issues.append(dict(code='operation_event_mismatch',operation_id=operation.id))
    return issues


async def reconcile(db,actor):
    actor=await builtin_actor(db,actor)
    instances=await handoff.list_instances(db,actor)
    issues=[]
    for item in instances:
        instance=await db.get(OAWorkflowInstance,item['instance_id'],populate_existing=True)
        subject=await resolve_subject(db,actor,instance)
        issues.extend(dict(scene=subject.scene,object_id=subject.object_id,
            leave_id=subject.object_id if subject.scene=='leave' else None,**issue)
            for issue in await reconciliation_issues(db,subject.row))
    return dict(ok=not issues,checked=len(instances),issues=issues,read_only=True)


async def management_actor(db,leave,actor):
    if actor:
        if actor.tenant_id!=leave.tenant_id: return None
        try:
            actor=await builtin_actor(db,actor)
            await handoff.admin_target(db,actor,leave,'write')
            return actor
        except AppException: return None
    department=await workflows.user_department(db,leave.tenant_id,leave.applicant_id)
    users=(await db.scalars(select(OAUser).join(OAMembership,
        (OAMembership.tenant_id==OAUser.tenant_id)&(OAMembership.user_id==OAUser.id)).where(
            OAUser.tenant_id==leave.tenant_id,OAUser.status=='active',OAMembership.department_id==department).order_by(OAUser.id))).all()
    for user in users:
        candidate=await current_identity(db,user)
        try:
            await handoff.admin_target(db,candidate,leave,'write')
            return candidate
        except AppException: continue
    return None


async def timer_plan(db,leave,instance,node,seat,now,*,ignore_operation_id=None):
    issues=await reconciliation_issues(db,leave,ignore_operation_id=ignore_operation_id)
    if issues: return 'pause','对账发现不一致，请管理员核对',None
    if not await approvals.seat_eligible(db,leave,node,seat): return 'pause','当前办理人资格失效，请管理员处理',None
    if not node.due_at: return 'pause','当前节点缺少截止时间，请管理员核对',None
    if now>=node.due_at and not seat.escalated:
        membership=await db.get(OAMembership,(leave.tenant_id,seat.effective_user_id),populate_existing=True)
        manager_id=membership.manager_id if membership else None
        seats=await approvals.seats_for(db,node)
        if seat.substituted or not manager_id or any(s.effective_user_id==manager_id for s in seats) or not await workflows.eligible_user(db,leave.tenant_id,manager_id,leave.applicant_id):
            return 'pause','超时升级没有合格上级或代理已失效，请管理员处理',None
        selector=seat.eligibility.get('selector',{})
        manager_department=await workflows.user_department(db,leave.tenant_id,manager_id)
        applicant_department=await workflows.user_department(db,leave.tenant_id,leave.applicant_id)
        if manager_department!=applicant_department and not (selector.get('kind')=='users' and manager_id in selector.get('user_ids',[])):
            return 'pause','超时上级不在允许接收范围内，请管理员处理',None
        return 'escalate',None,manager_id
    hours=instance.route_snapshot[node.ordinal]['timeout_hours']
    if now>=node.due_at-timedelta(hours=hours/2): return 'nudge',None,None
    return None,None,None


async def process_seat(db,actor,node_id,seat_id,now):
    leave,version,instance,node=await approvals.records(db,actor,node_id)
    seats=await approvals.seats_for(db,node)
    seat=next(s for s in seats if s.id==seat_id)
    if not approvals.active_round(leave,version,instance,node) or seat.state!='PENDING': return None
    kind,reason,manager_id=await timer_plan(db,leave,instance,node,seat,now)
    if not kind: return None
    route_revision=instance.route_revision
    async def perform(operation):
        row,current_version,current,node=await approvals.records(db,actor,node_id,lock=True)
        await handoff.admin_target(db,actor,row,'write')
        seats=await approvals.seats_for(db,node,lock=True)
        seat=next(s for s in seats if s.id==seat_id)
        if not approvals.active_round(row,current_version,current,node) or seat.state!='PENDING' or current.route_revision!=route_revision:
            raise invalid('定时任务已失效')
        current_kind,current_reason,manager=await timer_plan(db,row,current,node,seat,now,ignore_operation_id=operation.id)
        if current_kind!=kind: raise invalid('定时任务条件已变化')
        recipients=[]
        change=None
        if kind=='pause':
            row.state=current.state='PAUSED'
            current.pause_reason=current_reason
            current.revision+=1
            row.revision+=1
            recipients=[actor.user_id]
        elif kind=='escalate':
            change=await handoff.replace_seat(db,row,node,seats,seat,manager)
            seat.escalated=True
            current.route_revision+=1
            current.revision+=1
            row.revision+=1
            node.due_at=now+timedelta(hours=current.route_snapshot[node.ordinal]['timeout_hours'])
            recipients=[manager]
        else: recipients=[seat.effective_user_id]
        await db.flush()
        access={uid:('approval',OAAccessTarget(actor.tenant_id,uid)) for uid in recipients}
        if kind=='pause': access[actor.user_id]=('workflow_admin',await handoff.admin_target(db,actor,row,'write'))
        return CommandOutcome(result=dict(state=row.state,node_id=node_id,seat_id=seat_id,revision=current.revision),
            recipients=recipients,recipient_access=access,detail=dict(reason=current_reason,change=change,
                route_revision=current.route_revision,seat_id=seat_id,triggered_at=now.isoformat()))
    key=str(uuid5(NAMESPACE_URL,f'oa:timer:{node_id}:{route_revision}:{seat_id}:{kind}'))
    return await run_command(db,actor,OACommand(kind='workflow.'+kind,target_id=node_id,target_version=str(route_revision),
        operation_id=key,payload=dict(node_id=node_id,seat_id=seat_id,route_revision=route_revision,kind=kind),resource='workflow_admin',
        target=await handoff.admin_target(db,actor,leave,'write'),applicant_id=leave.applicant_id),perform)


async def scan(db,*,now=None,actor=None):
    now=now or datetime.now(timezone.utc)
    nodes=(await db.execute(select(OAWorkflowNode.id,OAWorkflowNode.instance_id).join(OAWorkflowInstance,
        (OAWorkflowInstance.id==OAWorkflowNode.instance_id)&(OAWorkflowInstance.tenant_id==OAWorkflowNode.tenant_id)).where(
            OAWorkflowNode.state=='ACTIVE',OAWorkflowInstance.state=='IN_REVIEW').order_by(OAWorkflowNode.id))).all()
    report=dict(processed=0,replayed=0,unmanaged=0,errors=[])
    for node_id,instance_id in nodes:
        try:
            # Discovery confers no authority; each command below refreshes and checks it.
            instance=await db.get(OAWorkflowInstance,instance_id,populate_existing=True)
            # Resolve tenant-scoped data before choosing an authorized management actor.
            discovery=OAAccessTarget(instance.tenant_id)
            subject=await resolve_subject(db,discovery,instance)
            leave=subject.row
            manager=await management_actor(db,leave,actor)
            if manager is None:
                report['unmanaged']+=1
                continue
            seat_ids=(await db.scalars(select(OAWorkflowSeat.id).where(
                OAWorkflowSeat.tenant_id==leave.tenant_id,OAWorkflowSeat.node_id==node_id,
                OAWorkflowSeat.state=='PENDING').order_by(OAWorkflowSeat.id))).all()
            for seat_id in seat_ids:
                outcome=await process_seat(db,manager,node_id,seat_id,now)
                if outcome:
                    report['replayed' if outcome.replayed else 'processed']+=1
        except AppException:
            continue
        except Exception:
            logger.exception('正式流程定时任务失败，节点 %s',node_id)
            report['errors'].append(dict(node_id=node_id,code='timer_failed'))
    return report
