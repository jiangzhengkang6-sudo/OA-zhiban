"""Built-in leave application request and response DTOs."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .common import PageResult


class LeaveApplicationCreate(BaseModel):
    leave_type: str
    start_at: datetime
    end_at: datetime
    reason: str = ""
    attachments: list[str] = Field(default_factory=list)


class LeaveApplicationPatch(BaseModel):
    leave_type: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    reason: Optional[str] = None
    attachments: Optional[list[str]] = None


class LeaveApplicationResponse(BaseModel):
    application_id: str
    thread_id: Optional[str] = None
    business_id: str
    user_id: str
    status: str
    version: int
    fields: dict
    precheck: Optional[dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class LeaveVersionResponse(BaseModel):
    version: int
    status: str
    fields: dict
    precheck: Optional[dict] = None
    created_at: Optional[datetime] = None


class LeaveApplicationPage(PageResult[LeaveApplicationResponse]):
    pass
