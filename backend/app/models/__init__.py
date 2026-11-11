"""
OA 智能体管理系统 - ORM 模型汇总模块。

集中导入所有 ORM 模型，确保 Base.metadata 完整注册（供 create_all 与 Alembic 使用）。
"""

from .identity import (OAUser, OADepartment, OAPosition, OAMembership, OARole,
                       OAPermission, OAUserRole, OARolePermission, OAAuthSession, OAAuthThrottle)
from .oa_workflow import (OAWorkflowDefinition, OAWorkflowVersion, OAWorkflowInstance,
    OAWorkflowNode, OAWorkflowSeat, OAWorkflowOperation, OAWorkflowEvent, OAWorkflowOutbox)
from .oa_leave import OALeave, OALeaveVersion, OALeaveBalance, OALeaveLedger, OALeaveAttachment
from .oa_reimbursement import OAReimbursement, OAReimbursementVersion, OAReimbursementAttachment
from .oa_ticket import OATicket,OATicketAssignmentRule,OATicketFeedback
from .oa_bridge import OABridgeConfirmation,OABridgeResult
from .assistant_draft import AssistantDraft
from .assistant_schedule import AssistantSchedule
from .oa_notification import OAUserContact,OANotification,OANotificationDelivery,OANotificationAttempt
from .oa_announcement import OAAnnouncement, OAAnnouncementRead
from .oa_meeting import OAMeeting, OAMeetingAttendee
from .meeting_transcription import MeetingTranscription, MeetingUtterance
from .oa_ai_scope import OAKnowledgeBinding, OAAgentPolicy, OAAgentPolicyVersion, OABusinessAudit
from .agent_thread import AgentThread
from .agent_message import AgentMessage
from .precheck_result import PrecheckResult
from .human_decision import HumanDecision
from .ticket_context import TicketContext
from .knowledge_document import KnowledgeDocument
from .knowledge_chunk import KnowledgeChunk
from .knowledge_source import KnowledgeSource
from .knowledge_version import KnowledgeVersion
from .knowledge_file import KnowledgeFile
from .audit_event import AuditEvent
from .agent_policy import AgentPolicy
from .idempotency_record import IdempotencyRecord
from .runtime_span import RuntimeSpan
from .approval_instance import ApprovalInstance
from .approval_node import ApprovalNode
from .approval_decision import ApprovalDecision
from .human_queue_item import HumanQueueItem
from .handoff_snapshot import HandoffSnapshot
from .ticket_draft import TicketDraft
from .leave_application import LeaveApplication
from .leave_application_version import LeaveApplicationVersion
from .leave_attachment import LeaveAttachment
from .ticket_record import TicketRecord
from .ticket_assignment_rule import TicketAssignmentRule
from .ticket_feedback import TicketFeedback
from .policy_version import PolicyVersion
from .audit_export import AuditExport
from .model_usage import ModelUsage
from .degradation_state import DegradationState
from .meeting_record import MeetingRecord
from .meeting_source import MeetingSource
from .meeting_segment import MeetingSegment
from .meeting_draft_version import MeetingDraftVersion
from .meeting_decision import MeetingDecision
from .document_record import DocumentRecord
from .document_draft_version import DocumentDraftVersion
from .email_record import EmailRecord
from .public_mail import PublicMailbox, PublicMailboxMember, PublicMailMessage, PublicMailImport
from .email_draft_version import EmailDraftVersion
from .work_task_batch import WorkTaskBatch
from .work_task_draft_version import WorkTaskDraftVersion
from .work_task import WorkTask
from .work_task_event import WorkTaskEvent
from .work_task_notification import WorkTaskNotification
from .report_record import ReportRecord, ReportVersion
from .oa_delegation import OAApprovalDelegation
from .contract_record import ContractRecord
from .contract_source import ContractSource
from .contract_review_version import ContractReviewVersion

__all__ = [
    'OAUser', 'OADepartment', 'OAPosition', 'OAMembership', 'OARole',
    'OAPermission', 'OAUserRole', 'OARolePermission', 'OAAuthSession', 'OAAuthThrottle',
    'AssistantSchedule',
    "WorkTaskBatch", "WorkTaskDraftVersion", "WorkTask", "WorkTaskEvent", "WorkTaskNotification",
    "ReportRecord", "ReportVersion", "ContractRecord", "ContractSource", "ContractReviewVersion",
    "EmailRecord",
    "EmailDraftVersion",
    "AgentThread",
    "AgentMessage",
    "PrecheckResult",
    "HumanDecision",
    "TicketContext",
    "KnowledgeDocument",
    "KnowledgeChunk",
    "KnowledgeSource",
    "KnowledgeVersion",
    "KnowledgeFile",
    "AuditEvent",
    "AgentPolicy",
    "IdempotencyRecord",
    "RuntimeSpan",
    "ApprovalInstance",
    "ApprovalNode",
    "ApprovalDecision",
    "HumanQueueItem",
    "HandoffSnapshot",
    "TicketDraft",
    "LeaveApplication",
    "LeaveApplicationVersion",
    "LeaveAttachment",
    "TicketRecord",
    "TicketAssignmentRule",
    "TicketFeedback",
    "PolicyVersion",
    "AuditExport",
    "ModelUsage",
    "DegradationState",
    "MeetingRecord",
    "MeetingSource",
    "MeetingSegment",
    "MeetingDraftVersion",
    "MeetingDecision",
    "DocumentRecord",
    "DocumentDraftVersion",
    "OAKnowledgeBinding",
    "OAAgentPolicy",
    "OAAgentPolicyVersion",
    "OABusinessAudit",
]
