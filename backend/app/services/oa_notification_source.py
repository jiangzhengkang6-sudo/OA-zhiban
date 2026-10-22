"""Resolve trusted event origins and recheck current business access."""
from sqlalchemy import or_, select
from ..core.errors import AppException
from ..models.identity import OAUser
from ..models.oa_ticket import OATicket
from ..models.oa_workflow import OAWorkflowOperation,OAWorkflowInstance,OAWorkflowNode,OAWorkflowSeat
from .oa_access_service import OAAccessTarget,authorize_oa,user_department,invalid
from .identity_service import current_identity
from .oa_workflow_subject import resolve_subject,subject_models


def intent_source(source, recipient):
    if not isinstance(source, dict) or source.get('kind') != 'intent' or source.get('recipient_id') != recipient:
        return {}
    if 'business' in source:
        business = source['business']
        if not isinstance(business, dict) or not isinstance(business.get('object_id'), str) or not business['object_id']:
            return {}
        resources = {'ticket': {'ticket', 'ticket_handle'}, 'leave': {'leave'}, 'reimbursement': {'reimbursement'}}
        if business.get('resource') not in resources.get(business.get('scene'), set()):
            return {}
    return source


async def check_business(db,actor,source):
    """Reauthorize a descriptor resolved from formal tenant business rows."""
    if source['scene']=='ticket':
        from . import oa_ticket_service as service
        await service.access(db,actor,source['object_id'],resource=source['resource'])
    elif source['scene']=='leave':
        from . import oa_leave_service as service
        await service.applicant_access(db,actor,source['object_id'])
    elif source['scene']=='reimbursement':
        from . import oa_reimbursement_service as service
        await service.applicant_access(db,actor,source['object_id'])
    else:
        raise invalid('通知业务来源无效')


async def business_source(db,actor,business_id):
    from ..models.oa_leave import OALeave
    from ..models.oa_reimbursement import OAReimbursement
    matches=[]
    for scene,model in (('ticket',OATicket),('leave',OALeave),('reimbursement',OAReimbursement)):
        rows=(await db.scalars(select(model).where(model.tenant_id==actor.tenant_id,
            or_(model.id==business_id,model.business_no==business_id)))).all()
        for row in rows:
            resource=('ticket' if row.owner_id==actor.user_id else 'ticket_handle') if scene=='ticket' else scene
            matches.append(dict(scene=scene,object_id=row.id,resource=resource))
    if len(matches)!=1: raise invalid('通知业务来源不存在或不唯一')
    await check_business(db,actor,matches[0])
    return matches[0]


async def describe(db,event,recipient):
    operation=await db.get(OAWorkflowOperation,event.operation_id)
    if not operation or operation.tenant_id!=event.tenant_id: return {}
    result=operation.result
    if event.action=='notification.intent':
        if result.get('recipient_id')!=recipient or operation.actor_id!=recipient: return {}
        return intent_source(result.get('source'), recipient)
    if event.action.startswith('ticket.'):
        row=await db.scalar(select(OATicket).where(OATicket.tenant_id==event.tenant_id,
            OATicket.id==result.get('id',event.target_id)))
        if not row: return {}
        return dict(kind='ticket',object_id=row.id,resource='ticket' if recipient==row.owner_id else 'ticket_handle')
    instance=None
    for instance_id in (event.detail.get('instance_id'),result.get('instance_id'),event.target_id):
        if instance_id:
            instance=await db.scalar(select(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id==event.tenant_id,OAWorkflowInstance.id==instance_id))
            if instance: break
    if instance is None:
        node=await db.scalar(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id==event.tenant_id,
            OAWorkflowNode.id==result.get('node_id',event.target_id)))
        if node is None:
            seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.tenant_id==event.tenant_id,OAWorkflowSeat.id==event.target_id))
            if seat: node=await db.get(OAWorkflowNode,seat.node_id)
        if node: instance=await db.get(OAWorkflowInstance,node.instance_id)
    if instance is None and event.action in {'leave.submit','reimbursement.submit'}:
        scene=event.action.split('.')[0]
        _,version_model,key,association=subject_models(scene)
        version=await db.scalar(select(version_model).where(version_model.tenant_id==event.tenant_id,
            getattr(version_model,key)==event.target_id,version_model.version==event.detail.get('submission_version')))
        if version:
            instance=await db.scalar(select(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id==event.tenant_id,
                getattr(OAWorkflowInstance,association)==version.id))
    if not instance or instance.tenant_id!=event.tenant_id: return {}
    subject=await resolve_subject(db,OAAccessTarget(event.tenant_id),instance)
    if recipient==subject.owner_id:
        return dict(kind='workflow',instance_id=instance.id,resource=instance.scene)
    if event.action=='workflow.pause' or event.action=='workflow.resume' and instance.state=='PAUSED':
        return dict(kind='workflow',instance_id=instance.id,resource='workflow_admin')
    nodes=(await db.scalars(select(OAWorkflowNode).join(OAWorkflowSeat,
        (OAWorkflowSeat.node_id==OAWorkflowNode.id)&(OAWorkflowSeat.tenant_id==OAWorkflowNode.tenant_id)).where(
        OAWorkflowNode.tenant_id==event.tenant_id,OAWorkflowNode.instance_id==instance.id,
        OAWorkflowSeat.effective_user_id==recipient,OAWorkflowNode.state.in_(['ACTIVE','DONE'])))).all()
    if event.action in {'workflow.nudge','workflow.escalate'}: nodes=[node for node in nodes if node.id==event.target_id]
    if event.action=='workflow.transfer': nodes=[node for node in nodes if node.id==event.detail.get('node_id')]
    return dict(kind='workflow',instance_id=instance.id,resource='approval',node_ids=sorted(set(node.id for node in nodes)))


async def allowed(db,notification):
    """False suppresses content; existing transport facts remain intact."""
    try:
        user=await db.scalar(select(OAUser).where(OAUser.tenant_id==notification.tenant_id,
            OAUser.id==notification.recipient_id).execution_options(populate_existing=True))
        actor=await current_identity(db,user)
        department=await user_department(db,actor.tenant_id,actor.user_id)
        if not department or department!=notification.department_id: return False
        await authorize_oa(db,actor,'notification','read',target=OAAccessTarget(actor.tenant_id,actor.user_id,department))
        source=notification.source
        if source.get('kind')=='intent':
            if not intent_source(source, actor.user_id): return False
            if source.get('business'): await check_business(db,actor,source['business'])
            return True
        if source.get('kind')=='ticket':
            from . import oa_ticket_service as tickets
            _,row=await tickets.access(db,actor,source['object_id'],resource=source['resource'])
            if source['resource']=='ticket_handle': return row.assignee_id==actor.user_id and row.state in {'OPEN','IN_PROGRESS'}
            return True
        if source.get('kind')!='workflow': return False
        instance=await db.scalar(select(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id==actor.tenant_id,
            OAWorkflowInstance.id==source['instance_id']).execution_options(populate_existing=True))
        if not instance: return False
        subject=await resolve_subject(db,actor,instance)
        if source['resource'] in {'leave','reimbursement','workflow_admin'}:
            if source['resource']=='workflow_admin' and (instance.state!='PAUSED' or subject.submission_version!=subject.row.submission_version): return False
            await authorize_oa(db,actor,source['resource'],'read',target=OAAccessTarget(actor.tenant_id,
                subject.owner_id,await user_department(db,actor.tenant_id,subject.owner_id)))
            return True
        from . import oa_approval_service as approvals
        for node_id in source.get('node_ids',[]):
            node=await db.get(OAWorkflowNode,node_id,populate_existing=True)
            if not node or node.tenant_id!=actor.tenant_id or node.instance_id!=instance.id: continue
            seats=await approvals.seats_for(db,node)
            for seat in seats:
                if seat.effective_user_id!=actor.user_id or not await approvals.seat_eligible(db,subject.row,node,seat): continue
                await authorize_oa(db,actor,'approval','read',target=OAAccessTarget(actor.tenant_id,actor.user_id))
                if node.kind=='cc' and seat.state=='CC' and subject.row.submission_version==subject.submission_version: return True
                if approvals.active_round(subject.row,subject.version,instance,node) and seat.state=='PENDING': return True
        return False
    except AppException:
        return False
