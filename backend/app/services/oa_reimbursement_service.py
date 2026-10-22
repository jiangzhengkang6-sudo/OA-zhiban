"""Versioned manual reimbursement authority in the caller's transaction."""
from datetime import datetime, timezone
from uuid import uuid4, uuid5, NAMESPACE_URL

from sqlalchemy import select
from ..models.oa_reimbursement import OAReimbursement,OAReimbursementVersion
from ..models.oa_workflow import OAWorkflowInstance,OAWorkflowNode,OAWorkflowSeat,OAWorkflowEvent
from ..schemas.oa_reimbursement import ReimbursementFields
from .oa_access_service import builtin_actor,authorize_oa,OAAccessTarget,tenant_row,invalid,revision_conflict,user_department
from .oa_command_service import OACommand,CommandOutcome,run_command
from . import oa_workflow_service as workflows

EDITABLE={'DRAFT','REJECTED','CANCELLED'}


async def target_for(db,actor,row):
    return OAAccessTarget(actor.tenant_id,row.applicant_id,await user_department(db,actor.tenant_id,row.applicant_id))


def view(row):
    actions=['edit','submit','upload'] if row.state in EDITABLE and not row.archived_at else []
    if row.state in {'IN_REVIEW','PAUSED'} and not row.archived_at: actions.append('withdraw')
    if row.state in {'APPROVED','REJECTED','CANCELLED'} and not row.archived_at: actions.append('archive')
    return dict(id=row.id,scene='reimbursement',business_no=row.business_no,applicant_id=row.applicant_id,
        department_id=row.department_id,workflow_definition_id=row.workflow_definition_id,fields=row.fields,
        revision=row.revision,submission_version=row.submission_version,state=row.state,
        archived_at=row.archived_at.isoformat() if row.archived_at else None,allowed_actions=actions)


async def applicant_access(db,actor,reimbursement_id,*,write=False,lock=False):
    actor=await builtin_actor(db,actor)
    row=await tenant_row(db,OAReimbursement,actor,reimbursement_id,lock=lock)
    await authorize_oa(db,actor,'reimbursement','write' if write else 'read',target=await target_for(db,actor,row))
    return actor,row


def check_editable(row,revision):
    if row.revision!=revision: raise revision_conflict()
    if row.state not in EDITABLE or row.archived_at: raise invalid('当前报销单不可编辑，请撤回或退回后重新提交')


async def detail(db,actor,reimbursement_id):
    actor,row=await applicant_access(db,actor,reimbursement_id)
    from . import oa_reimbursement_attachment_service as attachments
    result=view(row)
    result['attachments']=[attachments.metadata(item) for item in await attachments.refs(db,actor,row.id,row.fields.get('attachment_ids',[]))]
    if row.applicant_id!=actor.user_id: result['allowed_actions']=[]
    versions=(await db.scalars(select(OAReimbursementVersion).where(OAReimbursementVersion.tenant_id==actor.tenant_id,
        OAReimbursementVersion.reimbursement_id==row.id).order_by(OAReimbursementVersion.version))).all()
    result['versions']=[dict(id=v.id,version=v.version,workflow_version_id=v.workflow_version_id,fields=v.fields,
        amount_minor=v.amount_cents,currency=v.currency,attachments=v.attachments,precheck=v.precheck,differences=v.differences) for v in versions]
    instances=(await db.scalars(select(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id==actor.tenant_id,
        OAWorkflowInstance.reimbursement_version_id.in_([v.id for v in versions])))).all() if versions else []
    by_version={item.reimbursement_version_id:item for item in instances}
    result['pause_reason']=by_version[versions[-1].id].pause_reason if versions and versions[-1].id in by_version else None
    instance_ids=[item.id for item in instances]
    node_ids=select(OAWorkflowNode.id).where(OAWorkflowNode.tenant_id==actor.tenant_id,OAWorkflowNode.instance_id.in_(instance_ids))
    events=(await db.scalars(select(OAWorkflowEvent).where(OAWorkflowEvent.tenant_id==actor.tenant_id,
        OAWorkflowEvent.action=='approval.decide',OAWorkflowEvent.target_id.in_(node_ids)).order_by(OAWorkflowEvent.created_at))).all() if instance_ids else []
    result['history']=[dict(actor_id=e.actor_id,created_at=e.created_at.isoformat(),**e.detail)
        for e in events if e.detail.get('instance_id') in instance_ids]
    return result


async def list_reimbursements(db,actor):
    actor=await builtin_actor(db,actor)
    from .authorization_service import resource_clause
    rows=(await db.scalars(select(OAReimbursement).where(OAReimbursement.tenant_id==actor.tenant_id,
        resource_clause(actor,'reimbursement',OAReimbursement.applicant_id)).order_by(OAReimbursement.created_at.desc()))).all()
    result=[]
    for row in rows:
        await authorize_oa(db,actor,'reimbursement','read',target=await target_for(db,actor,row))
        item=view(row)
        if row.applicant_id!=actor.user_id: item['allowed_actions']=[]
        result.append(item)
    return result


async def create_draft(db,actor,payload):
    actor=await builtin_actor(db,actor)
    department=await user_department(db,actor.tenant_id,actor.user_id)
    target=OAAccessTarget(actor.tenant_id,actor.user_id,department)
    key=str(uuid5(NAMESPACE_URL,'oa:reimbursement:'+actor.tenant_id+':'+actor.user_id+':'+payload.operation_id))
    async def create(operation):
        await workflows.current_version(db,actor,payload.workflow_definition_id,scene='reimbursement')
        row=OAReimbursement(id=key,tenant_id=actor.tenant_id,business_no='R-'+uuid4().hex[:20].upper(),
            applicant_id=actor.user_id,department_id=department,workflow_definition_id=payload.workflow_definition_id,
            fields=payload.fields.model_dump(mode='json'),revision=1,submission_version=0,state='DRAFT')
        db.add(row)
        await db.flush()
        return CommandOutcome(result=view(row),changes=dict(after=dict(state='DRAFT')))
    return await run_command(db,actor,OACommand(kind='reimbursement.create',target_id=key,target_version='draft',
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='reimbursement',target=target,applicant_id=actor.user_id),create)


async def update_draft(db,actor,reimbursement_id,payload):
    actor,row=await applicant_access(db,actor,reimbursement_id,write=True)
    async def update(operation):
        _,current=await applicant_access(db,actor,reimbursement_id,write=True,lock=True)
        check_editable(current,payload.expected_revision)
        before=current.fields
        current.fields,current.revision=payload.fields.model_dump(mode='json'),current.revision+1
        await db.flush()
        return CommandOutcome(result=view(current),changes=dict(before=before,after=current.fields))
    return await run_command(db,actor,OACommand(kind='reimbursement.edit',target_id=row.id,target_version=str(payload.expected_revision),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='reimbursement',
        target=await target_for(db,actor,row),applicant_id=row.applicant_id),update)


async def submit(db,actor,reimbursement_id,payload):
    actor,row=await applicant_access(db,actor,reimbursement_id,write=True)
    from . import oa_reimbursement_attachment_service as attachments
    form=ReimbursementFields.model_validate(row.fields)
    manifest=await attachments.preflight(db,actor,row.id,form.attachment_ids)
    async def perform(operation):
        _,current=await applicant_access(db,actor,reimbursement_id,write=True,lock=True)
        check_editable(current,payload.expected_revision)
        if payload.requested_submission_version!=current.submission_version+1 or current.fields!=form.model_dump(mode='json'):
            raise revision_conflict()
        version=await workflows.current_version(db,actor,current.workflow_definition_id,scene='reimbursement')
        await attachments.verify_manifest(db,actor,current.id,manifest)
        route=await workflows.resolve_route(db,actor,version,form)
        previous=await db.scalar(select(OAReimbursementVersion).where(OAReimbursementVersion.tenant_id==actor.tenant_id,
            OAReimbursementVersion.reimbursement_id==current.id,OAReimbursementVersion.version==current.submission_version))
        changes={key:dict(before=previous.fields.get(key),after=value) for key,value in current.fields.items()
            if previous and previous.fields.get(key)!=value}
        snapshot=OAReimbursementVersion(id=str(uuid4()),tenant_id=actor.tenant_id,reimbursement_id=current.id,
            version=payload.requested_submission_version,workflow_version_id=version.id,fields=form.model_dump(mode='json'),
            amount_cents=form.amount_minor,currency=form.currency,attachments=manifest,
            precheck=dict(materials='pass',currency='CNY',amount_minor=form.amount_minor),differences=changes)
        db.add(snapshot)
        await db.flush()
        state='PAUSED' if route.pause_reasons else 'IN_REVIEW'
        instance=OAWorkflowInstance(id=str(uuid4()),tenant_id=actor.tenant_id,scene='reimbursement',
            reimbursement_version_id=snapshot.id,leave_version_id=None,route_snapshot=route.nodes,route_revision=1,revision=1,
            state=state,pause_reason='；'.join(route.pause_reasons)[:500] or None)
        db.add(instance)
        await db.flush()
        for index,planned in enumerate(route.nodes):
            node=OAWorkflowNode(id=str(uuid4()),tenant_id=actor.tenant_id,instance_id=instance.id,ordinal=index,
                node_key=planned['key'],kind=planned['kind'],mode=planned['mode'],state='WAITING',revision=1)
            db.add(node)
            await db.flush()
            for seat in planned['seats'] or [dict(user_id=None,valid=False,eligibility={})]:
                from ..models.identity import OAUser
                exists=await db.scalar(select(OAUser.id).where(OAUser.tenant_id==actor.tenant_id,OAUser.id==seat['user_id'])) if seat['user_id'] else None
                db.add(OAWorkflowSeat(tenant_id=actor.tenant_id,node_id=node.id,original_user_id=exists,effective_user_id=exists,
                    eligibility={**seat['eligibility'],'requested_user_id':seat['user_id']},state='PENDING',revision=1,substituted=False,escalated=False))
        before=current.state
        current.state,current.submission_version,current.revision=state,snapshot.version,current.revision+1
        await db.flush()
        recipients=await workflows.activate_next(db,instance,current) if state=='IN_REVIEW' else []
        current.state=instance.state
        await db.flush()
        return CommandOutcome(result=view(current),recipients=recipients,
            recipient_access={uid:('approval',OAAccessTarget(actor.tenant_id,uid)) for uid in recipients},
            detail=dict(submission_version=snapshot.version,workflow_version=version.version,pause_reason=instance.pause_reason),
            changes=dict(before=dict(state=before),after=dict(state=current.state)))
    return await run_command(db,actor,OACommand(kind='reimbursement.submit',target_id=row.id,target_version=str(payload.requested_submission_version),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='reimbursement',
        target=await target_for(db,actor,row),applicant_id=row.applicant_id),perform)


async def withdraw(db,actor,reimbursement_id,payload):
    actor,row=await applicant_access(db,actor,reimbursement_id,write=True)
    async def perform(operation):
        from .oa_approval_service import cancel_remaining
        _,current=await applicant_access(db,actor,reimbursement_id,write=True,lock=True)
        if current.revision!=payload.expected_revision: raise revision_conflict()
        if current.state not in {'IN_REVIEW','PAUSED'} or current.archived_at: raise invalid('当前报销单不能撤回')
        version=await db.scalar(select(OAReimbursementVersion).where(OAReimbursementVersion.tenant_id==actor.tenant_id,
            OAReimbursementVersion.reimbursement_id==current.id,OAReimbursementVersion.version==current.submission_version))
        instance=await db.scalar(select(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id==actor.tenant_id,
            OAWorkflowInstance.reimbursement_version_id==version.id).with_for_update().execution_options(populate_existing=True))
        before=current.state
        current.state=instance.state='CANCELLED'
        current.revision+=1
        instance.revision+=1
        await cancel_remaining(db,instance)
        await db.flush()
        return CommandOutcome(result=view(current),detail=dict(submission_version=version.version),
            changes=dict(before=dict(state=before),after=dict(state='CANCELLED')))
    return await run_command(db,actor,OACommand(kind='reimbursement.withdraw',target_id=row.id,target_version=str(payload.expected_revision),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='reimbursement',
        target=await target_for(db,actor,row),applicant_id=row.applicant_id),perform)


async def archive(db,actor,reimbursement_id,payload):
    actor,row=await applicant_access(db,actor,reimbursement_id,write=True)
    async def perform(operation):
        _,current=await applicant_access(db,actor,reimbursement_id,write=True,lock=True)
        if current.revision!=payload.expected_revision: raise revision_conflict()
        if current.state not in {'APPROVED','REJECTED','CANCELLED'} or current.archived_at: raise invalid('仅已结束且未归档的报销单可以归档')
        current.archived_at=datetime.now(timezone.utc)
        current.revision+=1
        await db.flush()
        return CommandOutcome(result=view(current))
    return await run_command(db,actor,OACommand(kind='reimbursement.archive',target_id=row.id,target_version=str(payload.expected_revision),
        operation_id=payload.operation_id,payload=payload.model_dump(mode='json'),resource='reimbursement',
        target=await target_for(db,actor,row),applicant_id=row.applicant_id),perform)
