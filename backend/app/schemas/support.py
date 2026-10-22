"""Support and authoritative ticket operation contracts."""

from typing import Any
from pydantic import BaseModel, Field


class TicketDuplicateCandidate(BaseModel):
    ticket_id: str
    score: float
    reason: str
    status: str


class TicketOperationResponse(BaseModel):
    ticket_id: str | None = None
    status: str
    category: str | None = None
    priority: str | None = None
    impact: str | None = None
    summary: str | None = None
    queue_id: str | None = None
    assignee_id: str | None = None
    assignment_rule_version: str | None = None
    assignment_error: dict[str, Any] | None = None
    duplicate_candidates: list[TicketDuplicateCandidate] = Field(default_factory=list)
    merged: bool = False


class TicketAssignmentRuleCreate(BaseModel):
    category: str
    impact: str = "个人"
    queue_id: str
    assignee_id: str | None = None
    rule_version: str
    priority: int = 0
    enabled: bool = True


class SupportQueueAssignment(BaseModel):
    assignee_id: str = Field(min_length=1, max_length=64)


class SupportQueueCompletion(BaseModel):
    resolution: str = Field(min_length=1, max_length=4000)
    status: str = Field(default="resolved", pattern="^(resolved|closed)$")


class SupportQueueItemResponse(BaseModel):
    queue_item_id: str
    tenant_id: str
    thread_id: str
    user_id: str
    scene: str
    reason_code: str
    status: str
    assignee_id: str | None = None
    context_summary: str | None = None
    snapshot: dict[str, Any] = Field(default_factory=dict)
    ticket_id: str | None = None
    ticket_status: str | None = None
    sla_status: str


class SupportQueueListResponse(BaseModel):
    items: list[SupportQueueItemResponse] = Field(default_factory=list)
    total: int
    page: int = 1
    page_size: int = 20


class TicketFeedbackCreate(BaseModel):
    resolved: bool
    comment: str = Field(default="", max_length=4000)
    idempotency_key: str = Field(min_length=1, max_length=128)


class TicketFeedbackResponse(BaseModel):
    feedback_id: str
    ticket_id: str
    ticket_status: str | None = None
    review_queue_item_id: str | None = None
    resolved: bool
