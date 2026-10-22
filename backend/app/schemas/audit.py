"""
OA 智能体管理系统 - 审计查询请求/响应模型。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AuditEventOut(BaseModel):
    """审计事件响应。

    Attributes:
        id: 事件 ID。
        trace_id: 追踪 ID。
        thread_id: 会话 ID。
        business_id: 业务单据号。
        actor_id: 操作者。
        action: 动作。
        target_type: 操作目标类型。
        target_id: 操作目标 ID。
        tool_name: 工具名。
        result: 结果。
        error_code: 错误码。
        policy_version: 策略版本。
        duration_ms: 耗时。
        created_at: 时间。
        input_summary: 输入摘要。
        output_summary: 输出摘要。
    """

    id: int | str
    trace_id: Optional[str] = None
    thread_id: Optional[str] = None
    business_id: Optional[str] = None
    actor_id: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    tool_name: Optional[str] = None
    result: Optional[str] = None
    error_code: Optional[str] = None
    policy_version: Optional[str] = None
    duration_ms: Optional[int] = None
    created_at: Optional[datetime] = None
    input_summary: Optional[dict] = None
    output_summary: Optional[dict] = None
