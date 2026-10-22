"""人工交接 DTO 与脱敏规则。"""

from typing import Any

from pydantic import BaseModel, Field


class HandoffContext(BaseModel):
    thread_id: str
    scene: str
    reason_code: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    faq_sources: list[dict[str, Any]] = Field(default_factory=list)


class HandoffResponse(BaseModel):
    queue_item_id: str
    status: str
    reason_code: str

