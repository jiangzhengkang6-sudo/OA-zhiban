"""
OA 智能体管理系统 - 中断恢复（HITL）请求/响应模型。

定义人工提交 approve/edit/reject 等决定的对外 DTO。
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class ResumeRequest(BaseModel):
    """恢复中断（提交人工决定）请求。

    Attributes:
        action: 动作（approve/edit/reject/confirm/cancel）。
        comment: 决策意见。
        edited_data: 编辑后的数据（edit 时）。
    """

    action: str = Field(description="动作：approve/edit/reject/confirm/cancel")
    comment: Optional[str] = Field(default="", description="决策意见")
    edited_data: Optional[dict[str, Any]] = Field(default=None, description="编辑后的数据")
    idempotency_key: Optional[str] = Field(default=None, max_length=128, description="审批决定幂等键；旧客户端可省略")


class ResumeResponse(BaseModel):
    """恢复中断响应。

    Attributes:
        status: 恢复后的会话状态。
        next_action: 下一步动作。
        trace_id: 追踪 ID。
    """

    status: str
    next_action: Optional[str] = None
    trace_id: str = ""
