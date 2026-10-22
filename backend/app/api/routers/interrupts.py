"""
OA 智能体管理系统 - 中断恢复接口路由。

提供 HITL 人工决定的提交入口：
    POST /api/agent/interrupts/{interrupt_id}/resume
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.context import get_trace_id
from ...core.errors import AppException, ErrorCode
from ...core.errors import not_found
from ...db.session import get_db
from ...repositories import thread_repo
from ...schemas.common import ok
from ...schemas.interrupt import ResumeRequest, ResumeResponse
from ...services import interrupt_service
from ...services.approval_service import get_instance
from ...services.idempotency_service import payload_digest
from ...models.approval_decision import ApprovalDecision
from ...models.human_decision import HumanDecision
from ...services.authorization_service import require_fresh_identity
from sqlalchemy import select
from ..deps import get_current_user

router = APIRouter(prefix="/agent/interrupts", tags=["agent-interrupts"])


@router.post("/{interrupt_id}/resume")
async def resume_interrupt(
    interrupt_id: str,
    payload: ResumeRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """提交人工决定（approve/edit/reject/confirm/cancel）并恢复图运行。

    Args:
        interrupt_id: pending 中断 ID。
        payload: 决定内容。
        session: 数据库会话。
        user: 当前登录用户。

    Returns:
        ApiResponse: 恢复后的状态与 next_action。
    """
    thread = await thread_repo.get_thread_by_interrupt_id(session, interrupt_id)
    from ...core.config import get_settings
    if get_settings().oa_provider == 'builtin':
        if thread is None:
            past = await session.scalar(select(HumanDecision).where(HumanDecision.interrupt_id == interrupt_id,
                HumanDecision.actor_id == user.user_id).order_by(HumanDecision.created_at.desc()).limit(1))
            if past:
                thread = await thread_repo.get_thread(session, past.thread_id)
        if thread is not None and thread.scene == 'ticket':
            from ...services.oa_ticket_graph_service import resume
            status, next_action = await resume(session, thread, user, interrupt_id, payload, interrupt_service.runtime)
            return ok(ResumeResponse(status=status, next_action=next_action, trace_id=get_trace_id()))
        if thread is not None and thread.scene == 'leave':
            from ...services.oa_leave_graph_service import resume
            status, next_action = await resume(session, thread, user, interrupt_id, payload, interrupt_service.runtime)
            return ok(ResumeResponse(status=status, next_action=next_action, trace_id=get_trace_id()))
        raise AppException(ErrorCode.DEPENDENCY_FAILED, '此中断尚未接通正式业务，请使用人工工作台', http_status=503)
    if thread is None:
        past = (await session.scalars(select(HumanDecision).where(
            HumanDecision.interrupt_id == interrupt_id, HumanDecision.actor_id == user.user_id
        ).order_by(HumanDecision.created_at.desc()).limit(1))).one_or_none()
        if past:
            old_thread = await thread_repo.get_thread(session, past.thread_id)
            if old_thread and old_thread.scene == "leave" and old_thread.tenant_id == user.tenant_id:
                instance = await get_instance(session, old_thread.id)
                key = payload.idempotency_key or f"interrupt:{interrupt_id}"
                recorded = (await session.scalars(select(ApprovalDecision).where(
                    ApprovalDecision.instance_id == instance.id,
                    ApprovalDecision.idempotency_key == key))).one_or_none() if instance else None
                if recorded:
                    digest = payload_digest({"actor_id": user.user_id, "action": payload.action,
                                             "comment": payload.comment or "", "edited_data": payload.edited_data or {}})
                    if recorded.payload_hash != digest:
                        raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "重复决定载荷不一致", http_status=409)
                    return ok(ResumeResponse(status={"pending_write": "APPROVED", "waiting_human": "WAITING_HUMAN",
                                                     "rejected": "REJECTED"}.get(recorded.result_status, "NEEDS_FIX"),
                                             next_action={"pending_write": "approved"}.get(
                                                 recorded.result_status, recorded.result_status), trace_id=get_trace_id()))
        raise not_found("中断不存在或已处理")

    await require_fresh_identity(user, {"approver"} if thread.scene == "leave" else (), session=session)
    if thread.tenant_id != user.tenant_id:
        raise not_found("中断不存在或已处理")

    status, next_action = await interrupt_service.resume_interrupt(
        session,
        thread,
        action=payload.action,
        comment=payload.comment or "",
        edited_data=payload.edited_data,
        actor_id=user.user_id,
        idempotency_key=payload.idempotency_key or f"interrupt:{interrupt_id}",
        expected_interrupt_id=interrupt_id,
    )
    return ok(
        ResumeResponse(
            status=status, next_action=next_action, trace_id=get_trace_id()
        )
    )
