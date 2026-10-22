"""可编辑工单草稿契约。"""

from typing import Any

from pydantic import BaseModel, Field, field_validator


ALLOWED_DRAFT_FIELDS = {"category", "priority", "impact", "summary"}
ALLOWED_PRIORITIES = {"low", "medium", "high", "urgent"}


class TicketDraftUpdate(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        unknown = set(value) - ALLOWED_DRAFT_FIELDS
        if unknown:
            raise ValueError(f"不允许修改字段: {sorted(unknown)}")
        if "priority" in value and value["priority"] not in ALLOWED_PRIORITIES:
            raise ValueError("priority 不合法")
        if "summary" in value and not str(value["summary"]).strip():
            raise ValueError("summary 不能为空")
        return value


class TicketDraftResponse(BaseModel):
    thread_id: str
    fields: dict[str, Any]
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    status: str

