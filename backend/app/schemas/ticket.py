"""
OA 智能体管理系统 - 工单相关请求/响应模型。
"""

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TicketCreateRequest(BaseModel):
    """创建工单请求（直接创建入口，需幂等键）。

    Attributes:
        category: 类别。
        priority: 优先级。
        summary: 问题摘要。
        context: 上下文。
        idempotency_key: 幂等键。
    """

    category: str = "其他"
    priority: str = "medium"
    summary: str
    context: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    thread_id: Optional[UUID] = Field(
        default=None,
        description="已完成 confirm 的智能助手会话 ID",
    )
    merge_ticket_id: Optional[str] = Field(default=None, description="已确认的重复工单目标")


class TicketStatusResponse(BaseModel):
    """工单状态响应。

    Attributes:
        ticket: 工单信息。
        timeline: 处理进度（简化）。
    """

    ticket: dict
    timeline: list[dict] = Field(default_factory=list)
