"""Formal ticket authority. No adapter, graph state or role-name authority."""
from uuid import uuid4,uuid5,NAMESPACE_URL
from sqlalchemy import select,or_
from ..models.oa_ticket import OATicket,OATicketAssignmentRule,OATicketFeedback
from ..models.oa_bridge import OABridgeResult
from ..models.oa_workflow import OAWorkflowOperation
from ..core.errors import AppException
from ..models.identity import OAUser
from .oa_access_service import builtin_actor,authorize_oa,OAAccessTarget,tenant_row,user_department,denied,invalid,revision_conflict
from .oa_command_service import OACommand,CommandOutcome,run_command
from .authorization_service import resource_clause,require_permission
from .identity_service import lock_tenant,current_identity
from . import oa_confirmation_service as confirmations

METHOD='create_or_merge_ticket'


def view(row):
    return dict(id=row.id,business_no=row.business_no,owner_id=row.owner_id,department_id=row.department_id,
        revision=row.revision,state=row.state,category=row.category,priority=row.priority,impact=row.impact,summary=row.summary,
        queue=row.queue,assignee_id=row.assignee_id,assignment_rule_version=row.assignment_rule_version,
        assignment_error=row.assignment_error,resolution_note=row.resolution_note)


async def target(db,actor,row):
    return OAAccessTarget(actor.tenant_id,row.owner_id,await user_department(db,actor.tenant_id,row.owner_id))


async def access(db,actor,ticket_id,*,action='read',resource=None,lock=False):
    actor=await builtin_actor(db,actor)
    row=await tenant_row(db,OATicket,actor,ticket_id,lock=lock)
    resource=resource or ('ticket' if row.owner_id==actor.user_id else 'ticket_handle')
    latest=await target(db,actor,row)
    await authorize_oa(db,actor,resource,action,target=latest)
    if resource=='ticket_handle' and row.department_id!=latest.department_id: raise denied()
    return actor,row


async def detail(db,actor,ticket_id):
    actor,row=await access(db,actor,ticket_id)
    result=view(row)
    result['merged_requests']=row.merged_requests
    feedback=(await db.scalars(select(OATicketFeedback).where(OATicketFeedback.tenant_id==actor.tenant_id,
        OATicketFeedback.ticket_id==row.id).order_by(OATicketFeedback.created_at))).all()
    result['feedback']=[dict(id=item.id,resolved=item.resolved,comment=item.comment,created_at=item.created_at.isoformat()) for item in feedback]
    return result


async def list_tickets(db,actor,*,handling=False):
    actor=await builtin_actor(db,actor)
    resource='ticket_handle' if handling else 'ticket'
    clause=resource_clause(actor,resource,OATicket.assignee_id if handling else OATicket.owner_id)
    if handling:
        # Department queue visibility follows current request owners, not old assignments.
        clause=resource_clause(actor,resource,OATicket.owner_id)
        clause=or_(clause,OATicket.assignee_id==actor.user_id)
    rows=(await db.scalars(select(OATicket).where(OATicket.tenant_id==actor.tenant_id,clause).order_by(OATicket.created_at.desc()))).all()
    result=[]
    for row in rows:
        try: await access(db,actor,row.id,resource=resource)
        except AppException as error:
            if error.http_status==403: continue
            raise
        result.append(view(row))
    return result


def proposal_values(payload):
    return payload.model_dump(mode='json',exclude={'confirmation_id'})


def object_binding(actor,payload):
    return payload.merge_ticket_id or actor.user_id,str(payload.expected_revision or 0)


async def owner_authority(db,actor,payload):
    actor=await builtin_actor(db,actor)
    department=await user_department(db,actor.tenant_id,actor.user_id)
    await authorize_oa(db,actor,'ticket','write',target=OAAccessTarget(actor.tenant_id,actor.user_id,department))
    if not department: raise invalid('当前账号缺少有效部门')
    await confirmations.validate_thread(db,actor,payload.thread_id)
    if payload.merge_ticket_id:
        _,row=await access(db,actor,payload.merge_ticket_id,action='write',resource='ticket')
        if row.owner_id!=actor.user_id: raise denied()
    return actor,department


async def candidates(db,actor,summary):
    from .ticket_service import duplicate_score
    rows=(await db.scalars(select(OATicket).where(OATicket.tenant_id==actor.tenant_id,OATicket.owner_id==actor.user_id,
        OATicket.state.in_(['OPEN','IN_PROGRESS'])).order_by(OATicket.updated_at.desc()).limit(100))).all()
    matches=[]
    for row in rows:
        score=duplicate_score(summary,row.summary)
        if score: matches.append(dict(id=row.id,revision=row.revision,summary=row.summary,state=row.state,score=score[0],reason=score[1]))
    return sorted(matches,key=lambda item:item['score'],reverse=True)[:20]


async def prepare(db,actor,payload):
    actor,_=await owner_authority(db,actor,payload)
    if payload.merge_ticket_id:
        _,row=await access(db,actor,payload.merge_ticket_id,action='write',resource='ticket')
        if row.revision!=payload.expected_revision: raise revision_conflict()
        if row.state not in {'OPEN','IN_PROGRESS'}: raise invalid('仅可合并本人尚未结束的工单')
    object_id,version=object_binding(actor,payload)
    result=await confirmations.issue(db,actor,thread_id=payload.thread_id,action='ticket.merge' if payload.merge_ticket_id else 'ticket.create',
        object_id=object_id,object_version=version,payload=proposal_values(payload))
    result.update(proposal=proposal_values(payload),duplicate_candidates=await candidates(db,actor,payload.summary))
    return result


async def eligible_handler(db,tenant,user_id,department):
    if not user_id: return False
    user=await db.scalar(select(OAUser).where(OAUser.id==user_id,OAUser.tenant_id==tenant,OAUser.status=='active'))
    if user is None or await user_department(db,tenant,user_id)!=department: return False
    member=await current_identity(db,user)
    try: await authorize_oa(db,member,'ticket_handle','write',target=OAAccessTarget(tenant,None,department))
    except AppException: return False
    return True


async def assignment(db,actor,department,category,impact):
    rows=(await db.scalars(select(OATicketAssignmentRule).where(OATicketAssignmentRule.tenant_id==actor.tenant_id,
        OATicketAssignmentRule.department_id==department).order_by(OATicketAssignmentRule.version.desc()))).all()
    latest={}
    for row in rows: latest.setdefault(row.code,row)
    matches=[row for row in latest.values() if row.enabled and row.category in {category,'*'} and row.impact in {impact,'*'}]
    if not matches: return dict(queue=None,assignee_id=None,assignment_rule_id=None,assignment_rule_version=None,assignment_error='暂无有效分派规则，请人工领取')
    chosen=sorted(matches,key=lambda row:(row.category==category,row.impact==impact,row.priority,row.code),reverse=True)[0]
    eligible=await eligible_handler(db,actor.tenant_id,chosen.assignee_id,department)
    return dict(queue=chosen.queue,assignee_id=chosen.assignee_id if eligible else None,assignment_rule_id=chosen.id,
        assignment_rule_version=chosen.version,assignment_error=None if eligible else '缺少有效处理人，请人工领取')


async def create_or_merge(db,actor,payload,*,confirmation_id):
    actor,department=await owner_authority(db,actor,payload)
    await lock_tenant(db,actor.tenant_id)
    existing=await db.scalar(select(OABridgeResult).where(OABridgeResult.tenant_id==actor.tenant_id,
        OABridgeResult.actor_id==actor.user_id,OABridgeResult.method==METHOD,OABridgeResult.original_key==payload.operation_id))
    if existing: await access(db,actor,existing.target_id,action='write',resource='ticket')
    object_id,version=object_binding(actor,payload)
    values=dict(thread_id=payload.thread_id,action='ticket.merge' if payload.merge_ticket_id else 'ticket.create',
        object_id=object_id,object_version=version,payload=proposal_values(payload))
    # A consumed binding permits only its original command replay, checked by run_command.
    await confirmations.binding(db,actor,confirmation_id,**values)
    command_target=str(uuid5(NAMESPACE_URL,'ticket-command:'+actor.tenant_id+':'+actor.user_id+':'+payload.operation_id))
    async def perform(operation):
        await confirmations.consume(db,actor,confirmation_id,operation.id,**values)
        if payload.merge_ticket_id:
            _,row=await access(db,actor,payload.merge_ticket_id,action='write',resource='ticket',lock=True)
            if row.revision!=payload.expected_revision: raise revision_conflict()
            if row.state not in {'OPEN','IN_PROGRESS'}: raise invalid('目标工单已结束，请重新确认')
            row.merged_requests=[*row.merged_requests,dict(category=payload.category,priority=payload.priority,impact=payload.impact,
                summary=payload.summary,operation_id=operation.id)]
            row.revision+=1
        else:
            row=OATicket(id=str(uuid4()),tenant_id=actor.tenant_id,owner_id=actor.user_id,department_id=department,
                business_no='T'+uuid4().hex[:20].upper(),revision=1,state='OPEN',category=payload.category,priority=payload.priority,
                impact=payload.impact,summary=payload.summary,merged_requests=[],**await assignment(db,actor,department,payload.category,payload.impact))
            db.add(row)
        await db.flush()
        result={**view(row),'merged':bool(payload.merge_ticket_id)}
        await confirmations.record_result(db,actor,method=METHOD,original_key=payload.operation_id,target_id=row.id,
            target_version=row.revision,operation_id=operation.id,result=result)
        recipients=[row.assignee_id] if row.assignee_id else []
        return CommandOutcome(result=result,recipients=recipients,
            recipient_access={uid:('ticket_handle',OAAccessTarget(actor.tenant_id,None,department)) for uid in recipients},
            detail=dict(ticket_id=row.id,merged=bool(payload.merge_ticket_id)),changes=dict(after=dict(state=row.state,revision=row.revision)))
    return await run_command(db,actor,OACommand(kind='ticket.create_or_merge',target_id=command_target,target_version='1',
        operation_id=payload.operation_id,payload={**proposal_values(payload),'confirmation_id':confirmation_id},resource='ticket',
        target=OAAccessTarget(actor.tenant_id,actor.user_id,department),applicant_id=actor.user_id),perform)


async def get_result(db,actor,original_key):
    actor=await builtin_actor(db,actor)
    require_permission(actor,'ticket','read')
    row=await db.scalar(select(OABridgeResult).where(OABridgeResult.tenant_id==actor.tenant_id,
        OABridgeResult.actor_id==actor.user_id,OABridgeResult.method==METHOD,OABridgeResult.original_key==original_key))
    if row is None: return None
    await access(db,actor,row.target_id,resource='ticket')
    operation=await db.scalar(select(OAWorkflowOperation).where(OAWorkflowOperation.tenant_id==actor.tenant_id,
        OAWorkflowOperation.id==row.operation_id,OAWorkflowOperation.actor_id==actor.user_id))
    return operation.result if operation else None


async def handle(db,actor,ticket_id,payload):
    actor,row=await access(db,actor,ticket_id,action='write',resource='ticket_handle')
    async def perform(operation):
        _,current=await access(db,actor,ticket_id,action='write',resource='ticket_handle',lock=True)
        if current.revision!=payload.expected_revision: raise revision_conflict()
        if current.state not in {'OPEN','IN_PROGRESS'}: raise invalid('工单已结束，不能继续办理')
        if not await eligible_handler(db,actor.tenant_id,actor.user_id,current.department_id): raise denied()
        before=dict(state=current.state,assignee_id=current.assignee_id,revision=current.revision)
        if payload.action=='claim':
            if current.assignee_id and await eligible_handler(db,actor.tenant_id,current.assignee_id,current.department_id):
                raise invalid('工单已分派给有效处理人')
            current.assignee_id=actor.user_id
            current.state='IN_PROGRESS'
            current.assignment_error=None
        elif payload.action=='reassign':
            if current.assignee_id!=actor.user_id:
                await authorize_oa(db,actor,'ticket_admin','write',target=OAAccessTarget(actor.tenant_id,None,current.department_id))
            if not await eligible_handler(db,actor.tenant_id,payload.target_user_id,current.department_id): raise invalid('目标人员无本部门工单办理权限')
            current.assignee_id=payload.target_user_id
            current.assignment_error=None
        else:
            if current.assignee_id!=actor.user_id: raise denied()
            current.state='IN_PROGRESS' if payload.action=='start' else 'RESOLVED'
            if payload.action=='resolve': current.resolution_note=payload.note
        current.revision+=1
        await db.flush()
        return CommandOutcome(result=view(current),recipients=[current.owner_id],
            recipient_access={current.owner_id:('ticket',await target(db,actor,current))},
            detail=dict(action=payload.action,ticket_id=current.id),changes=dict(before=before,after=dict(state=current.state,assignee_id=current.assignee_id,revision=current.revision)))
    async def reauthorize(): await access(db,actor,ticket_id,action='write',resource='ticket_handle')
    return await run_command(db,actor,OACommand(kind='ticket.handle',target_id=row.id,target_version=str(payload.expected_revision),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='ticket_handle',target=await target(db,actor,row),
        applicant_id=row.owner_id,reauthorize=reauthorize),perform)


async def feedback(db,actor,ticket_id,payload):
    actor,row=await access(db,actor,ticket_id,action='write',resource='ticket')
    async def perform(operation):
        _,current=await access(db,actor,ticket_id,action='write',resource='ticket',lock=True)
        if current.revision!=payload.expected_revision: raise revision_conflict()
        if current.state not in {'RESOLVED','CLOSED'}: raise invalid('工单尚未进入可反馈状态')
        db.add(OATicketFeedback(tenant_id=actor.tenant_id,ticket_id=current.id,actor_id=actor.user_id,operation_id=operation.id,
            resolved=payload.resolved,comment=payload.comment))
        before=current.state
        current.state='CLOSED' if payload.resolved else 'OPEN'
        current.revision+=1
        if not payload.resolved and not await eligible_handler(db,actor.tenant_id,current.assignee_id,current.department_id):
            current.assignee_id=None
            current.assignment_error='缺少有效处理人，请人工领取'
        await db.flush()
        recipients=[current.assignee_id] if not payload.resolved and current.assignee_id else []
        return CommandOutcome(result=view(current),recipients=recipients,
            recipient_access={uid:('ticket_handle',OAAccessTarget(actor.tenant_id,None,current.department_id)) for uid in recipients},
            detail=dict(resolved=payload.resolved,ticket_id=current.id),changes=dict(before=dict(state=before),after=dict(state=current.state)))
    return await run_command(db,actor,OACommand(kind='ticket.feedback',target_id=row.id,target_version=str(payload.expected_revision),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='ticket',target=await target(db,actor,row),
        applicant_id=row.owner_id),perform)


def rule_view(row):
    return dict(id=row.id,department_id=row.department_id,code=row.code,version=row.version,category=row.category,impact=row.impact,
        queue=row.queue,assignee_id=row.assignee_id,priority=row.priority,enabled=row.enabled)


async def list_rules(db,actor,department_id):
    actor=await builtin_actor(db,actor)
    await authorize_oa(db,actor,'ticket_admin','read',target=OAAccessTarget(actor.tenant_id,None,department_id))
    rows=(await db.scalars(select(OATicketAssignmentRule).where(OATicketAssignmentRule.tenant_id==actor.tenant_id,
        OATicketAssignmentRule.department_id==department_id).order_by(OATicketAssignmentRule.code,OATicketAssignmentRule.version.desc()))).all()
    latest={}
    for row in rows: latest.setdefault(row.code,rule_view(row))
    return list(latest.values())


async def save_rule(db,actor,payload):
    actor=await builtin_actor(db,actor)
    access_target=OAAccessTarget(actor.tenant_id,None,payload.department_id)
    await authorize_oa(db,actor,'ticket_admin','write',target=access_target)
    async def perform(operation):
        current=await db.scalar(select(OATicketAssignmentRule).where(OATicketAssignmentRule.tenant_id==actor.tenant_id,
            OATicketAssignmentRule.department_id==payload.department_id,OATicketAssignmentRule.code==payload.code)
            .order_by(OATicketAssignmentRule.version.desc()).limit(1))
        if (current.version if current else None)!=payload.expected_version: raise revision_conflict()
        if payload.assignee_id and not await eligible_handler(db,actor.tenant_id,payload.assignee_id,payload.department_id):
            raise invalid('目标人员无本部门工单办理权限')
        row=OATicketAssignmentRule(tenant_id=actor.tenant_id,version=(current.version+1 if current else 1),
            **payload.model_dump(exclude={'operation_id','expected_version'}))
        db.add(row)
        await db.flush()
        return CommandOutcome(result=rule_view(row),detail=dict(code=row.code,version=row.version))
    return await run_command(db,actor,OACommand(kind='ticket.rule.save',target_id=str(uuid5(NAMESPACE_URL,actor.tenant_id+':'+payload.department_id+':'+payload.code)),
        target_version=str(payload.expected_version or 0),operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),
        resource='ticket_admin',target=access_target),perform)
