"""
OA 智能体管理系统 - 审计服务。

提供审计事件统一写入入口，从 contextvars 自动取 trace_id / actor / policy_version，
覆盖会话/路由/工具/预检/检索/回答/人工决定/写入/通知/重试/异常/配置/降级等事件。
敏感摘要由调用方在写入前脱敏。
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.context import get_current_user, get_policy_version, get_trace_id
from ..repositories import audit_repo


async def audit(
    session: AsyncSession,
    action: str,
    *,
    thread_id: Optional[UUID] = None,
    business_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    input_summary: Optional[dict] = None,
    output_summary: Optional[dict] = None,
    result: Optional[str] = "success",
    error_code: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    """写入一条审计事件（自动注入上下文信息）。

    Args:
        session: 数据库会话。
        action: 事件动作。
        thread_id: 会话 ID。
        business_id: 业务单据号。
        actor_id: 操作者（缺省取当前用户）。
        target_type: 目标类型。
        target_id: 目标 ID。
        tool_name: 工具名。
        input_summary: 输入摘要。
        output_summary: 输出摘要。
        result: 结果。
        error_code: 错误码。
        duration_ms: 耗时。
    """
    from ..core.config import get_settings
    if get_settings().oa_provider == "builtin":
        from .oa_scope_service import record_audit
        from ..core.context import CurrentUser
        current = get_current_user()
        if current is not None:
            await record_audit(session, actor=current, resource=target_type or "system", action=action,
                object_type=target_type, object_id=target_id, source_type=target_type,
                source_id=business_id, result=result or "success",
                detail={"input": input_summary or {}, "output": output_summary or {}, "error_code": error_code,
                        "thread_id": str(thread_id) if thread_id else None})
            return

    trace_id = get_trace_id() or None
    if actor_id is None:
        user = get_current_user()
        actor_id = user.user_id if user else "system"
    policy_version = get_policy_version() or None

    await audit_repo.add_event(
        session,
        trace_id=trace_id,
        action=action,
        thread_id=thread_id,
        business_id=business_id,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        tool_name=tool_name,
        input_summary=input_summary,
        output_summary=output_summary,
        result=result,
        error_code=error_code,
        policy_version=policy_version,
        duration_ms=duration_ms,
    )


def _truncate(data: dict, max_len: int = 512) -> dict:
    """对摘要字段做长度截断与脱敏兜底。

    Args:
        data: 待处理的摘要字典。
        max_len: 字符串值最大长度。

    Returns:
        dict: 处理后的摘要字典。
    """
    if not data:
        return data
    out = {}
    for k, v in data.items():
        if isinstance(v, str) and len(v) > max_len:
            v = v[:max_len] + "..."
        out[k] = v
    return out
