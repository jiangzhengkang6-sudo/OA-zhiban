"""DTOs for the text-only meeting agent."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .common import PageResult


MeetingSourceType = Literal["paste", "import", "api"]
MeetingStatus = Literal[
    "CREATED",
    "PROCESSING",
    "DRAFT_READY",
    "REVIEWING",
    "PAUSED",
    "CONFIRMED",
    "REJECTED",
]


class MeetingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    source_type: MeetingSourceType = "paste"
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("会议标题不能为空")
        return value.strip()


class MeetingGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    expected_version: int | None = Field(default=None, ge=1)


class MeetingCreateRequest(MeetingInput):
    pass


class MeetingDraftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: MeetingDraftDTO
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)


class MeetingDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["confirm", "reject", "regenerate"]
    reason: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)


class MeetingSegmentDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=64)
    ordinal: int = Field(ge=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    text: str = Field(min_length=1)
    locator: str = Field(min_length=1, max_length=128)
    text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: str = Field(min_length=1, max_length=256)


class MeetingDecisionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    confidence: Literal["explicit", "inferred", "needs_confirmation"] = "needs_confirmation"


class MeetingActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    assignee_candidate: str | None = None
    due_at_candidate: str | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    source_refs: list[str] = Field(min_length=1)
    needs_confirmation: bool = True


class MeetingDraftDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    topics: list[str] = Field(default_factory=list)
    decisions: list[MeetingDecisionCandidate] = Field(default_factory=list)
    action_items: list[MeetingActionItem] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def nonblank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("纪要摘要不能为空")
        return value


class MeetingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_id: str
    thread_id: str | None = None
    status: MeetingStatus
    title: str
    version: int | None = None
    segments: list[MeetingSegmentDTO] = Field(default_factory=list)
    draft: MeetingDraftDTO | None = None
    available_actions: list[str] = Field(default_factory=list)
    trace_id: str = ""
    external_writes: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MeetingSummary(BaseModel):
    meeting_id: str
    thread_id: str | None = None
    title: str
    status: MeetingStatus
    version: int | None = None
    available_actions: list[str] = Field(default_factory=list)
    external_writes: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MeetingPage(PageResult[MeetingSummary]):
    pass

