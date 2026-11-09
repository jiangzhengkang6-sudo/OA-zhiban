"""Independent business tasks and immutable candidate review contracts."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkTaskCommandBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(default=0, ge=0)


class WorkTaskSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_type: Literal["meeting", "ticket", "approval", "email"]
    source_id: str = Field(min_length=1, max_length=64)
    source_version: int | None = Field(default=None, ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)


class WorkTaskCandidateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    candidate_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    assignee_id: str | None = Field(default=None, max_length=64)
    due_at: datetime | None = None
    priority: Literal["low", "normal", "high"] = "normal"
    sensitive: bool = False
    source_refs: list[str] = Field(min_length=1, max_length=10)

    @field_validator("due_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("A timezone-aware deadline is required")
        return value


class WorkTaskDraftDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[WorkTaskCandidateDTO] = Field(min_length=1, max_length=50)


class WorkTaskDraftUpdate(WorkTaskCommandBase):
    draft: WorkTaskDraftDTO


class WorkTaskDecision(WorkTaskCommandBase):
    action: Literal["confirm", "reject"]
    selected_candidate_ids: list[str] = Field(default_factory=list, max_length=50)
    metadata_confirmed: bool = False
    risk_acknowledged: bool = False
    reason: str = Field(default="", max_length=2000)


class WorkTaskBatchResponse(BaseModel):
    batch_id: str
    thread_id: str
    source_type: str
    source_id: str
    source_version: str
    source: dict
    status: str
    version: int
    draft: WorkTaskDraftDTO | None
    available_actions: list[str]
    task_ids: list[str]
    error: dict | None
    created_at: datetime
    updated_at: datetime
    external_writes: Literal[False] = False


class WorkTaskUpdate(WorkTaskCommandBase):
    title: str = Field(min_length=1, max_length=255)
    assignee_id: str = Field(min_length=1, max_length=64)
    due_at: datetime
    priority: Literal["low", "normal", "high"] = "normal"
    sensitive: bool = False
    metadata_confirmed: bool = False
    risk_acknowledged: bool = False

    _deadline = field_validator("due_at")(WorkTaskCandidateDTO.timezone_required.__func__)


class WorkTaskCommand(WorkTaskCommandBase):
    action: Literal["start", "progress", "complete", "cancel", "archive"]
    progress: int | None = Field(default=None, ge=0, le=100)
    comment: str = Field(default="", max_length=2000)


class WorkTaskResponse(BaseModel):
    task_id: str
    batch_id: str
    title: str
    creator_id: str
    assignee_id: str
    due_at: datetime
    priority: str
    sensitive: bool
    status: str
    progress: int
    version: int
    deadline_version: int
    source_refs: list[str]
    source: dict | None
    available_actions: list[str]
    created_at: datetime
    updated_at: datetime
    external_writes: Literal[False] = False


class WorkTaskPage(BaseModel):
    items: list[WorkTaskResponse]
    total: int
    page: int
    page_size: int
