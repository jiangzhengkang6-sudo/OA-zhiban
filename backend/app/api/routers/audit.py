"""
OA 智能体管理系统 - 审计接口路由。

提供审计事件的条件检索（按用户/业务号/trace_id/时间/动作）：
    GET /api/audit/events
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...repositories import audit_repo
from ...core.config import get_settings
from ...services import oa_scope_service
from ...schemas.audit import AuditEventOut
from ...schemas.common import PageResult, ok
from ..deps import require_audit_access

router = APIRouter(prefix="/audit", tags=["audit"])


def _to_out(e) -> AuditEventOut:
    """将 ORM 事件转换为 DTO。

    Args:
        e: 审计 ORM 对象。

    Returns:
        AuditEventOut: DTO。
    """
    return AuditEventOut(
        id=e.id,
        trace_id=e.trace_id,
        thread_id=str(e.thread_id) if e.thread_id else None,
        business_id=e.business_id,
        actor_id=e.actor_id,
        action=e.action,
        target_type=e.target_type,
        target_id=e.target_id,
        tool_name=e.tool_name,
        result=e.result,
        error_code=e.error_code,
        policy_version=e.policy_version,
        duration_ms=e.duration_ms,
        created_at=e.created_at,
        input_summary=e.input_summary,
        output_summary=e.output_summary,
    )


@router.get("/events")
async def query_events(
    trace_id: Optional[str] = Query(default=None),
    thread_id: Optional[UUID] = Query(default=None),
    business_id: Optional[str] = Query(default=None),
    actor_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    start_time: Optional[datetime] = Query(default=None),
    end_time: Optional[datetime] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    user=Depends(require_audit_access),
):
    """按条件检索审计事件（仅管理员/审计）。

    Args:
        trace_id: 追踪 ID。
        thread_id: 会话 ID。
        business_id: 业务单据号。
        actor_id: 操作者。
        action: 动作。
        start_time: 起始时间。
        end_time: 结束时间。
        page: 页码。
        page_size: 每页条数。
        session: 数据库会话。
        user: 当前用户（需 admin 角色）。

    Returns:
        ApiResponse: 分页审计事件。
    """
    if get_settings().oa_provider == "builtin":
        rows = await oa_scope_service.visible_audits(session, actor=user, trace_id=trace_id,
            thread_id=thread_id, business_id=business_id, actor_id=actor_id, action=action,
            start_time=start_time, end_time=end_time)
        total = len(rows)
        rows = rows[(page - 1) * page_size:page * page_size]
        items = [AuditEventOut(id=row.id, trace_id=row.trace_id, thread_id=(row.detail or {}).get('thread_id'),
            business_id=row.source_id or row.object_id, actor_id=row.actor_id, action=row.action,
            target_type=row.object_type, target_id=row.object_id, tool_name=row.resource,
            result=row.result, error_code=None, policy_version=row.policy_version,
            duration_ms=None, created_at=row.created_at, input_summary=(row.detail or {}).get("input", {}),
            output_summary=(row.detail or {}).get("output", {})) for row in rows]
        return ok(PageResult(items=[item.model_dump() for item in items], total=total,
                             page=page, page_size=page_size))
    items, total = await audit_repo.query_events(
        session,
        meeting_tenant_id=user.tenant_id,
        trace_id=trace_id,
        thread_id=thread_id,
        business_id=business_id,
        actor_id=actor_id,
        action=action,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )
    return ok(
        PageResult(
            items=[_to_out(e).model_dump() for e in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    )
