"""Structured task-center DTOs."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .common import PageResult


class TaskResponsibility(BaseModel):
    role: str
    user_id: Optional[str] = None
    display_name: Optional[str] = None
    waiting_since: Optional[datetime] = None


class TaskSummary(BaseModel):
    task_id: str
    task_type: str
    business_id: Optional[str] = None
    business_status: str
    next_action: Optional[str] = None
    responsibility: TaskResponsibility
    available_actions: list[str] = Field(default_factory=list)
    pause_reason: Optional[dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskPage(PageResult[TaskSummary]):
    pass
