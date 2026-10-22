"""Manual leave authority; version snapshots never depend on an agent graph."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4, uuid5, NAMESPACE_URL

from sqlalchemy import select
from ..models.oa_leave import OALeave, OALeaveVersion
from ..models.oa_workflow import OAWorkflowDefinition, OAWorkflowInstance, OAWorkflowNode, OAWorkflowSeat
from ..schemas.oa_leave import NormalizedLeaveFields
from .oa_access_service import (builtin_actor, authorize_oa, OAAccessTarget, tenant_row,
    invalid, revision_conflict, user_department)
from .oa_command_service import OACommand, CommandOutcome, run_command
from . import oa_workflow_service as workflows, oa_balance_service as balances

EDITABLE = {'DRAFT','REJECTED','CANCELLED'}


async def target_for(db,actor,row):
    return OAAccessTarget(actor.tenant_id,row.applicant_id,await user_department(db,actor.tenant_id,row.applicant_id))


def view(row):
    actions = ['edit','submit','upload'] if row.state in EDITABLE and not row.archived_at else []
    if row.state in {'IN_REVIEW','PAUSED'} and not row.archived_at: actions.append('withdraw')
    if row.state in {'APPROVED','REJECTED','CANCELLED'} and not row.archived_at: actions.append('archive')
    return dict(id=row.id,business_no=row.business_no,applicant_id=row.applicant_id,department_id=row.department_id,
        workflow_definition_id=row.workflow_definition_id,fields=row.fields,revision=row.revision,
        submission_version=row.submission_version,state=row.state,
        archived_at=row.archived_at.isoformat() if row.archived_at else None,allowed_actions=actions)


async def applicant_access(db,actor,leave_id,*,write=False,lock=False):
    actor = await builtin_actor(db,actor)
    row = await tenant_row(db,OALeave,actor,leave_id,lock=lock)
    await authorize_oa(db,actor,'leave','write' if write else 'read',target=await target_for(db,actor,row))
    return actor,row


def check_editable(row,revision):
    if row.revision != revision: raise revision_conflict()
    if row.state not in EDITABLE or row.archived_at: raise invalid('当前申请不可编辑，请撤回或退回后重新提交')


async def detail(db,actor,leave_id):
    actor,row = await applicant_access(db,actor,leave_id)
    result = view(row)
    from . import oa_attachment_service as attachments
    result['attachments'] = [attachments.metadata(a) for a in await attachments.refs(db,actor,row.id,row.fields.get('attachment_ids',[]))]
    if row.applicant_id != actor.user_id: result['allowed_actions'] = []
    versions = (await db.scalars(select(OALeaveVersion).where(OALeaveVersion.tenant_id==actor.tenant_id,
        OALeaveVersion.leave_id==row.id).order_by(OALeaveVersion.version))).all()
    result['versions'] = [dict(id=v.id,version=v.version,workflow_version_id=v.workflow_version_id,
        fields=v.fields,attachments=v.attachments,precheck=v.precheck,differences=v.differences) for v in versions]
    instance = await db.scalar(select(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id==actor.tenant_id,
        OAWorkflowInstance.leave_version_id==versions[-1].id)) if versions else None
    result['pause_reason'] = instance.pause_reason if instance else None
    from ..models.oa_workflow import OAWorkflowEvent
    instance_ids = list((await db.scalars(select(OAWorkflowInstance.id).where(OAWorkflowInstance.tenant_id==actor.tenant_id,
        OAWorkflowInstance.leave_version_id.in_([v.id for v in versions])))).all())
    node_ids = select(OAWorkflowNode.id).where(OAWorkflowNode.tenant_id==actor.tenant_id,OAWorkflowNode.instance_id.in_(instance_ids))
    events = (await db.scalars(select(OAWorkflowEvent).where(OAWorkflowEvent.tenant_id==actor.tenant_id,
        OAWorkflowEvent.action=='approval.decide',OAWorkflowEvent.target_id.in_(node_ids)).order_by(OAWorkflowEvent.created_at))).all() if instance_ids else []
    result['history'] = [dict(actor_id=e.actor_id,created_at=e.created_at.isoformat(),**e.detail)
        for e in events if e.detail.get('instance_id') in instance_ids]
    return result


async def list_leaves(db,actor):
    actor = await builtin_actor(db,actor)
    from .authorization_service import resource_clause
    rows = (await db.scalars(select(OALeave).where(OALeave.tenant_id==actor.tenant_id,
        resource_clause(actor,'leave',OALeave.applicant_id)).order_by(OALeave.created_at.desc()))).all()
    result = []
    for row in rows:
        await authorize_oa(db,actor,'leave','read',target=await target_for(db,actor,row))
        item = view(row)
        if row.applicant_id != actor.user_id: item['allowed_actions']=[]
        result.append(item)
    return result


async def create_draft(db,actor,payload):
    actor = await builtin_actor(db,actor)
    department = actor.depts[0] if actor.depts else None
    target = OAAccessTarget(actor.tenant_id,actor.user_id,department)
    leave_id = str(uuid5(NAMESPACE_URL,'oa:leave:'+actor.tenant_id+':'+actor.user_id+':'+payload.operation_id))
    async def create(operation):
        definition = await tenant_row(db,OAWorkflowDefinition,actor,payload.workflow_definition_id)
        if not department or definition.department_id != department: raise invalid('请选择当前部门的流程')
        row = OALeave(id=leave_id,tenant_id=actor.tenant_id,business_no='QJ-'+uuid4().hex[:24],
            applicant_id=actor.user_id,department_id=department,workflow_definition_id=definition.id,
            fields=payload.fields.model_dump(mode='json'),state='DRAFT',revision=1,submission_version=0)
        db.add(row)
        await db.flush()
        return CommandOutcome(result=view(row))
    return await run_command(db,actor,OACommand(kind='leave.create',target_id=leave_id,target_version='draft',
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='leave',target=target,applicant_id=actor.user_id),create)


async def update_draft(db,actor,leave_id,payload):
    actor,row = await applicant_access(db,actor,leave_id,write=True)
    async def update(operation):
        _,row = await applicant_access(db,actor,leave_id,write=True,lock=True)
        check_editable(row,payload.expected_revision)
        row.fields,row.revision = payload.fields.model_dump(mode='json'),row.revision+1
        await db.flush()
        return CommandOutcome(result=view(row))
    return await run_command(db,actor,OACommand(kind='leave.edit',target_id=leave_id,target_version=str(payload.expected_revision),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='leave',
        target=await target_for(db,actor,row),applicant_id=row.applicant_id),update)


async def submit(db,actor,leave_id,payload):
    actor,row = await applicant_access(db,actor,leave_id,write=True)
    # File IO and scanner latency must stay outside the serialized business transaction.
    from . import oa_attachment_service as attachments
    form = NormalizedLeaveFields.model_validate(row.fields)
    manifest = await attachments.preflight(db,actor,leave_id,form.attachment_ids)
    async def perform(operation):
        _,row = await applicant_access(db,actor,leave_id,write=True,lock=True)
        check_editable(row,payload.expected_revision)
        if payload.requested_submission_version != row.submission_version+1: raise revision_conflict()
        if row.fields != form.model_dump(mode='json'): raise revision_conflict()
        version = await workflows.current_version(db,actor,row.workflow_definition_id)
        package = workflows.validate_definition(version.package)
        if form.leave_type in package.rules.required_attachments and not manifest: raise invalid('该假种需要上传证明材料')
        await attachments.verify_manifest(db,actor,row.id,manifest)
        conflict = await db.scalar(select(OALeaveVersion.id).join(OALeave,
            (OALeave.id==OALeaveVersion.leave_id)&(OALeave.tenant_id==OALeaveVersion.tenant_id)&
            (OALeave.submission_version==OALeaveVersion.version)).where(OALeave.tenant_id==actor.tenant_id,
            OALeave.applicant_id==actor.user_id,OALeave.id!=row.id,OALeave.state.in_(['IN_REVIEW','PAUSED','APPROVED']),
            OALeaveVersion.start_date<=form.end_date,OALeaveVersion.end_date>=form.start_date))
        if conflict: raise invalid('日期与审批中、暂停或已通过的请假重叠')
        route = await workflows.resolve_route(db,actor,version,form)
        previous = await db.scalar(select(OALeaveVersion).where(OALeaveVersion.tenant_id==actor.tenant_id,
            OALeaveVersion.leave_id==row.id,OALeaveVersion.version==row.submission_version))
        changes = {key:dict(before=previous.fields.get(key),after=value) for key,value in row.fields.items()
            if previous and previous.fields.get(key)!=value}
        snapshot = OALeaveVersion(id=str(uuid4()),tenant_id=actor.tenant_id,leave_id=row.id,version=payload.requested_submission_version,
            workflow_version_id=version.id,fields=form.model_dump(mode='json'),attachments=manifest,
            precheck=dict(materials='pass',calendar_days=form.days),differences=changes,
            leave_type=form.leave_type,start_date=form.start_date,end_date=form.end_date,days=form.days)
        db.add(snapshot)
        await db.flush()
        state = 'PAUSED' if route.pause_reasons else 'IN_REVIEW'
        instance = OAWorkflowInstance(id=str(uuid4()),tenant_id=actor.tenant_id,leave_version_id=snapshot.id,
            route_snapshot=route.nodes,route_revision=1,revision=1,state=state,pause_reason='；'.join(route.pause_reasons)[:500] or None)
        db.add(instance)
        await db.flush()
        for index,planned in enumerate(route.nodes):
            node = OAWorkflowNode(id=str(uuid4()),tenant_id=actor.tenant_id,instance_id=instance.id,ordinal=index,
                node_key=planned['key'],kind=planned['kind'],mode=planned['mode'],state='WAITING',revision=1)
            db.add(node)
            await db.flush()
            for seat in planned['seats'] or [dict(user_id=None,valid=False,eligibility={})]:
                from ..models.identity import OAUser
                exists = await db.scalar(select(OAUser.id).where(OAUser.tenant_id==actor.tenant_id,OAUser.id==seat['user_id'])) if seat['user_id'] else None
                db.add(OAWorkflowSeat(tenant_id=actor.tenant_id,node_id=node.id,original_user_id=exists,effective_user_id=exists,
                    eligibility={**seat['eligibility'],'requested_user_id':seat['user_id']},state='PENDING',revision=1,
                    substituted=False,escalated=False))
        row.state,row.submission_version,row.revision = state,snapshot.version,row.revision+1
        await db.flush()
        recipients = []
        if state=='IN_REVIEW':
            recipients = await activate_next(db,instance,row)
            row.state=instance.state
        await balances.settle(db,row,snapshot,operation,'RESERVE')
        recipient_access = {uid:('approval',OAAccessTarget(actor.tenant_id,uid,row.department_id)) for uid in recipients}
        return CommandOutcome(result=view(row),recipients=recipients,recipient_access=recipient_access,
            detail=dict(submission_version=snapshot.version,workflow_version=version.version,pause_reason=instance.pause_reason))
    return await run_command(db,actor,OACommand(kind='leave.submit',target_id=row.id,target_version=str(payload.requested_submission_version),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='leave',target=await target_for(db,actor,row),
        applicant_id=row.applicant_id),perform)


async def activate_next(db,instance,leave):
    return await workflows.activate_next(db,instance,leave)


async def withdraw(db,actor,leave_id,payload):
    actor,row = await applicant_access(db,actor,leave_id,write=True)
    async def perform(operation):
        from .oa_approval_service import cancel_remaining
        _,current = await applicant_access(db,actor,leave_id,write=True,lock=True)
        if current.revision!=payload.expected_revision: raise revision_conflict()
        if current.state not in {'IN_REVIEW','PAUSED'} or current.archived_at: raise invalid('当前申请不能撤回')
        version = await db.scalar(select(OALeaveVersion).where(OALeaveVersion.tenant_id==actor.tenant_id,
            OALeaveVersion.leave_id==leave_id,OALeaveVersion.version==current.submission_version))
        instance = await db.scalar(select(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id==actor.tenant_id,
            OAWorkflowInstance.leave_version_id==version.id).with_for_update().execution_options(populate_existing=True))
        current.state=instance.state='CANCELLED'
        current.revision+=1
        instance.revision+=1
        await cancel_remaining(db,instance)
        await balances.settle(db,current,version,operation,'RELEASE')
        await db.flush()
        return CommandOutcome(result=view(current),detail=dict(submission_version=version.version))
    outcome = await run_command(db,actor,OACommand(kind='leave.withdraw',target_id=leave_id,target_version=str(payload.expected_revision),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='leave',
        target=await target_for(db,actor,row),applicant_id=row.applicant_id),perform)
    outcome.current_revision=row.revision
    outcome.allowed_actions=view(row)['allowed_actions']
    return outcome


async def archive(db,actor,leave_id,payload):
    actor,row = await applicant_access(db,actor,leave_id,write=True)
    async def perform(operation):
        _,current = await applicant_access(db,actor,leave_id,write=True,lock=True)
        if current.revision!=payload.expected_revision: raise revision_conflict()
        if current.state not in {'APPROVED','REJECTED','CANCELLED'} or current.archived_at: raise invalid('仅已结束且未归档的申请可以归档')
        current.archived_at=datetime.now(timezone.utc)
        current.revision+=1
        await db.flush()
        return CommandOutcome(result=view(current))
    return await run_command(db,actor,OACommand(kind='leave.archive',target_id=leave_id,target_version=str(payload.expected_revision),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='leave',
        target=await target_for(db,actor,row),applicant_id=row.applicant_id),perform)
