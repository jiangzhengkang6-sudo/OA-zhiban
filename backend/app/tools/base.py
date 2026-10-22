"""
OA 智能体管理系统 - 工具执行基座。

提供工具调用的统一包装：白名单校验、权限重校验入口、审计（调用前 pending、成功/失败
后回填结果）与耗时统计。所有业务工具调用都应经由 call_tool 包装执行。
"""

import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import AuditAction, ErrorCode
from ..core.errors import AppException
from ..services import audit_service, policy_service
from ..services import runtime_trace_service
from ..services.authorization_service import authorize_tool
from ..core.context import get_current_user, get_trace_id


async def call_tool(
    db: AsyncSession,
    *,
    scene: str,
    tool_name: str,
    input_summary: Optional[dict] = None,
    fn: Callable[[], Awaitable[Any]],
    thread_id=None,
    business_id: Optional[str] = None,
    actor=None,
) -> Any:
    """以白名单 + 权限 + 审计约束执行一次工具调用。

    Args:
        db: 数据库会话。
        scene: 当前场景。
        tool_name: 工具名。
        input_summary: 工具输入摘要（脱敏）。
        fn: 实际工具执行协程。
        thread_id: 关联会话 ID。
        business_id: 业务单据号。

    Returns:
        Any: 工具返回结果。

    Raises:
        AppException: 工具不在白名单、或 fn 执行失败时。
    """
    try:
        current = actor if actor is not None else get_current_user()
        active = await policy_service.get_thresholds(
            db, scene, user_id=getattr(current, "user_id", None),
            dept_id=(getattr(current, "depts", None) or [None])[0],
            tenant_id=getattr(current, "tenant_id", None),
        )
        await authorize_tool(current, scene, tool_name, session=db,
                       policy_tools=active.get("allowed_tools"))
    except AppException as exc:
        await audit_service.audit(db, AuditAction.TOOL_CALLED.value,
            thread_id=thread_id, business_id=business_id, tool_name=tool_name,
            result="fail", error_code=exc.code.value)
        raise
    start = time.monotonic()
    started_at = datetime.now(timezone.utc)
    current_user = current
    try:
        result = await fn()
        duration_ms = int((time.monotonic() - start) * 1000)
        try:
            await runtime_trace_service.record_span(
                db, tenant_id=getattr(current_user, "tenant_id", "unknown"),
                trace_id=get_trace_id(),
                node_name="tool_call", tool_name=tool_name, started_at=started_at,
                finished_at=datetime.now(timezone.utc), status="success",
                thread_id=thread_id,
            )
        except Exception:
            pass
        await audit_service.audit(
            db,
            AuditAction.TOOL_CALLED.value,
            thread_id=thread_id,
            business_id=business_id,
            tool_name=tool_name,
            input_summary=input_summary,
            output_summary=_safe_summary(result),
            result="success",
            duration_ms=duration_ms,
        )
        return result
    except AppException as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        try:
            await runtime_trace_service.record_span(
                db, tenant_id=getattr(current_user, "tenant_id", "unknown"),
                trace_id=get_trace_id(),
                node_name="tool_call", tool_name=tool_name, started_at=started_at,
                finished_at=datetime.now(timezone.utc), status="error",
                error_code=exc.code.value, thread_id=thread_id,
            )
        except Exception:
            pass
        await audit_service.audit(
            db,
            AuditAction.TOOL_CALLED.value,
            thread_id=thread_id,
            business_id=business_id,
            tool_name=tool_name,
            input_summary=input_summary,
            result="fail",
            error_code=exc.code.value,
            duration_ms=duration_ms,
        )
        raise
    except Exception as exc:  # 兜底：非业务异常
        duration_ms = int((time.monotonic() - start) * 1000)
        try:
            await runtime_trace_service.record_span(
                db, tenant_id=getattr(current_user, "tenant_id", "unknown"),
                trace_id=get_trace_id(),
                node_name="tool_call", tool_name=tool_name, started_at=started_at,
                finished_at=datetime.now(timezone.utc), status="error",
                error_code=ErrorCode.INTERNAL_ERROR.value, thread_id=thread_id,
            )
        except Exception:
            pass
        await audit_service.audit(
            db,
            AuditAction.TOOL_CALLED.value,
            thread_id=thread_id,
            business_id=business_id,
            tool_name=tool_name,
            input_summary=input_summary,
            result="fail",
            error_code=ErrorCode.INTERNAL_ERROR.value,
            duration_ms=duration_ms,
        )
        raise


def _safe_summary(result: Any, max_len: int = 256) -> dict:
    """将工具结果转换为安全的审计摘要（截断长文本）。

    Args:
        result: 工具返回结果。
        max_len: 字符串值最大长度。

    Returns:
        dict: 摘要字典。
    """
    if result is None:
        return {}
    if isinstance(result, dict):
        out = {}
        for k, v in result.items():
            if isinstance(v, str) and len(v) > max_len:
                v = v[:max_len] + "..."
            out[k] = v
        return out
    if isinstance(result, (str, int, float, bool)):
        return {"value": str(result)[:max_len]}
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return {"type": type(result).__name__}
