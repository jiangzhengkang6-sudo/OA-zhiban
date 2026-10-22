"""Operations and controlled export API contracts."""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AuditExportRequest(BaseModel):
    trace_id: Optional[str] = None
    thread_id: Optional[UUID] = None
    business_id: Optional[str] = None
    actor_id: Optional[str] = None
    action: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    page_size: int = Field(default=1000, ge=1, le=10000)


class AuditExportOut(BaseModel):
    id: UUID
    requested_by: str
    status: str
    filters: dict
    row_count: int
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    download_url: Optional[str] = None


class DegradationCreateRequest(BaseModel):
    scene: str = Field(min_length=1, max_length=16)
    scope_type: Literal["global", "tenant", "dept", "user"] = "global"
    scope_value: Optional[str] = Field(default=None, max_length=64)
    enabled: bool = True
    new_task_action: Literal["fallback", "reject"] = "fallback"
    inflight_action: Literal["continue", "pause"] = "continue"
    reason: str = Field(min_length=1, max_length=2000)


class DegradationOut(BaseModel):
    id: UUID
    scene: str
    scope_type: str
    scope_value: Optional[str] = None
    enabled: bool
    new_task_action: str
    inflight_action: str
    reason: str
    created_by: str
    restored_by: Optional[str] = None
    restored_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
