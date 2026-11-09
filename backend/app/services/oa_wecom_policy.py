"""Fail-closed group allowlist resolved only from trusted business events."""
from sqlalchemy import select
from ..models.oa_workflow import OAWorkflowOutbox, OAWorkflowEvent, OAWorkflowNode, OAWorkflowSeat

LABELS = {'approval': '有待审批事项', 'nudge': '有审批催办事项', 'exception': '有流程异常待处理',
          'ticket': '有工单待处理', 'meeting': '有会议邀请', 'meeting_change': '会议安排有变更',
          'meeting_cancel': '有会议取消通知'}


async def classify(db, notification, settings):
    outbox = await db.get(OAWorkflowOutbox, notification.source_outbox_id)
    event = await db.get(OAWorkflowEvent, outbox.event_id) if outbox else None
    if not event or event.tenant_id != notification.tenant_id:
        return None, 'wecom_policy_blocked'
    cutover = settings.wecom_policy_activated_at
    if cutover is None or event.created_at < cutover:
        return None, 'wecom_history_isolated'
    source, action = notification.source, event.action
    category = None
    if source.get('kind') == 'meeting':
        from ..models.oa_meeting import OAMeeting
        meeting = await db.get(OAMeeting, source['object_id'])
        if meeting and meeting.tenant_id == notification.tenant_id:
            if action == 'meeting.publish' and meeting.state == 'SCHEDULED': category = 'meeting'
            if action == 'meeting.save' and event.detail.get('external_fields_changed') and meeting.state == 'SCHEDULED': category = 'meeting_change'
            if action == 'meeting.cancel' and meeting.state == 'CANCELLED': category = 'meeting_cancel'
    elif source.get('kind') == 'ticket' and source.get('resource') == 'ticket_handle':
        if action == 'ticket.create_or_merge' and not event.detail.get('merged'): category = 'ticket'
        if action == 'ticket.feedback' and event.detail.get('resolved') is False: category = 'ticket'
        if action == 'ticket.handle' and event.detail.get('action') == 'reassign': category = 'ticket'
    elif source.get('kind') == 'workflow':
        if source.get('resource') == 'workflow_admin' and action == 'workflow.pause': category = 'exception'
        if source.get('resource') == 'approval' and action in {
                'leave.submit','reimbursement.submit','approval.decide','workflow.transfer','workflow.resume','workflow.nudge','workflow.escalate'}:
            pending = await db.scalar(select(OAWorkflowSeat.id).join(OAWorkflowNode,
                (OAWorkflowNode.id == OAWorkflowSeat.node_id) & (OAWorkflowNode.tenant_id == OAWorkflowSeat.tenant_id)).where(
                OAWorkflowNode.tenant_id == notification.tenant_id,
                OAWorkflowNode.id.in_(source.get('node_ids', [])), OAWorkflowNode.state == 'ACTIVE',
                OAWorkflowNode.kind != 'cc', OAWorkflowSeat.state == 'PENDING',
                OAWorkflowSeat.effective_user_id == notification.recipient_id))
            if pending: category = 'nudge' if action == 'workflow.nudge' else 'approval'
    if not category: return None, 'wecom_policy_blocked'
    object_id = source.get('instance_id') or source.get('object_id')
    return dict(category=category, event_key=event.id,
                business_key=source['kind'] + ':' + str(object_id)), None
