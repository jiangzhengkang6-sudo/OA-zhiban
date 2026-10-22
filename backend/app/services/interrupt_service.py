"""
OA 智能体管理系统 - 中断恢复服务。

封装 HITL 人工决定的落库、LangGraph 恢复与状态更新，是 interrupt/resume 协议的
服务端实现。决定写入 human_decision 表后再 resume 图，确保人工决定可审计、防篡改。
"""

import hashlib
import json
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from ..core.enums import AuditAction, HumanAction, ThreadStatus
from ..core.errors import AppException, ErrorCode
from ..graph.graph_service import extract_interrupt, runtime
from ..models.agent_thread import AgentThread
from ..models.human_decision import HumanDecision
from ..repositories import thread_repo
from ..services import audit_service
from ..services import approval_service
from ..db.session import async_session_factory
from ..models.approval_decision import ApprovalDecision
from .idempotency_service import payload_digest

# next_action -> ThreadStatus 映射
NEXT_ACTION_STATUS = {
    "route": ThreadStatus.ROUTING.value,
    "waiting_human": ThreadStatus.WAITING_HUMAN.value,
    "needs_fix": ThreadStatus.NEEDS_FIX.value,
    "approved": ThreadStatus.APPROVED.value,
    "rejected": ThreadStatus.REJECTED.value,
    "paused": ThreadStatus.PAUSED.value,
    "degraded": ThreadStatus.PAUSED.value,
    "human": ThreadStatus.WAITING_HUMAN.value,
    "answered": ThreadStatus.COMPLETED.value,
    "cancelled": ThreadStatus.COMPLETED.value,
    "completed": ThreadStatus.COMPLETED.value,
}


def map_next_action(next_action: Optional[str]) -> str:
    """将图节点的 next_action 映射为编排状态。

    Args:
        next_action: 图返回的下一步动作。

    Returns:
        str: 编排状态（ThreadStatus）。
    """
    return NEXT_ACTION_STATUS.get(next_action or "", ThreadStatus.PAUSED.value)


async def resume_interrupt(
    session: AsyncSession,
    thread: AgentThread,
    *,
    action: str,
    comment: str,
    edited_data: Optional[dict],
    actor_id: str,
    idempotency_key: str = "",
    expected_interrupt_id: str = "",
) -> tuple[str, Optional[str]]:
    if thread.scene in {"document", "email", "work_task", "report", "contract"}:
        raise AppException(ErrorCode.INVALID_STATE, "请通过对应工作台提交当前草稿版本", http_status=422)
    if thread.scene == "meeting":
        raise AppException(ErrorCode.INVALID_STATE, "请通过会议决定接口提交当前草稿版本", http_status=422)
    if thread.scene != "leave":
        return await _resume_locked(session, thread, action=action, comment=comment,
            edited_data=edited_data, actor_id=actor_id, idempotency_key=idempotency_key)
    # Session-level advisory lock spans the graph checkpoint and the thread
    # projection commit, without holding an approval row lock that graph nodes
    # also need. PostgreSQL releases it automatically on connection failure.
    async with async_session_factory() as mutex_session:
        connection = await mutex_session.connection()
        key = str(thread.id)
        await connection.execute(text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"), {"key": key})
        try:
            await session.refresh(thread)
            if thread.current_interrupt_id != expected_interrupt_id:
                instance = await approval_service.get_instance(session, thread.id)
                previous = (await session.scalars(select(ApprovalDecision).where(
                    ApprovalDecision.instance_id == instance.id,
                    ApprovalDecision.idempotency_key == idempotency_key))).one_or_none() if instance else None
                if previous is None:
                    raise AppException(ErrorCode.INTERRUPT_ALREADY_HANDLED, "中断已处理", http_status=409)
                digest = payload_digest({"actor_id": actor_id, "action": action,
                    "comment": comment or "", "edited_data": edited_data or {}})
                if previous.payload_hash != digest:
                    raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "重复决定载荷不一致", http_status=409)
                return thread.status, ({"APPROVED": "approved", "REJECTED": "rejected"}.get(
                    thread.status, "waiting_human" if thread.status == "WAITING_HUMAN" else "paused"))
            snapshot = await runtime.get_state(thread.id)
            pending = extract_interrupt(snapshot)
            if not pending or pending[0] != expected_interrupt_id:
                raise AppException(ErrorCode.INTERRUPT_ALREADY_HANDLED, "审批中断与当前图状态不一致，请刷新任务", http_status=409)
            return await _resume_locked(session, thread, action=action, comment=comment,
                edited_data=edited_data, actor_id=actor_id, idempotency_key=idempotency_key)
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key})


async def _resume_locked(
    session: AsyncSession,
    thread: AgentThread,
    *, action: str, comment: str, edited_data: Optional[dict], actor_id: str,
    idempotency_key: str,
) -> tuple[str, Optional[str]]:
    """提交人工决定并恢复图运行。

    Args:
        session: 数据库会话。
        thread: 会话记录。
        action: 决定动作。
        comment: 意见。
        edited_data: 编辑数据。
        actor_id: 决策者。

    Returns:
        tuple[str, Optional[str]]: (新状态, next_action)。
    """
    allowed_actions = {
        HumanAction.APPROVE.value,
        HumanAction.EDIT.value,
        HumanAction.REJECT.value,
        HumanAction.CONFIRM.value,
        HumanAction.CANCEL.value,
    }
    if action not in allowed_actions:
        raise AppException(
            ErrorCode.BAD_REQUEST,
            "不支持的人工操作",
            http_status=400,
            detail={"allowed_actions": sorted(allowed_actions)},
        )

    snapshot = await runtime.get_state(thread.id)
    state_values = snapshot.values if snapshot else {}
    interrupt = extract_interrupt(snapshot) if snapshot else None
    interrupt_payload = interrupt[1] if interrupt and isinstance(interrupt[1], dict) else {}
    intent = state_values.get("intent") or interrupt_payload.get("intent") or thread.scene
    if intent == "leave":
        if action not in {
            HumanAction.APPROVE.value,
            HumanAction.EDIT.value,
            HumanAction.REJECT.value,
        }:
            raise AppException(ErrorCode.INVALID_STATE, "当前请假中断不支持该操作", http_status=422)
        # The database's active node is authoritative; a historic route in a
        # checkpoint must never authorize a later or already retired approver.
        if await approval_service.get_instance(session, thread.id) is None:
            await approval_service.adopt_legacy_pending(session, thread, interrupt_payload)
        result_status = await approval_service.record_decision(
            session, thread.id, actor_id, action, comment, edited_data, idempotency_key
        )
        await session.commit()
    else:
        if interrupt_payload.get("type") == "ticket_confirm" and action not in {
            HumanAction.CONFIRM.value,
            HumanAction.CANCEL.value,
            HumanAction.EDIT.value,
        }:
            raise AppException(
                ErrorCode.INVALID_STATE,
                "当前工单中断不支持该操作",
                http_status=422,
            )
        if actor_id != thread.user_id:
            raise AppException(ErrorCode.FORBIDDEN, "只有会话发起人可以确认该操作", http_status=403)

    decision = {
        "action": action,
        "comment": comment or "",
        "edited_data": edited_data,
        "actor_id": actor_id,
        "idempotency_key": idempotency_key,
    }
    payload_hash = hashlib.sha256(
        json.dumps(decision, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    # 1. 写兼容旧数据的人工决定（正式决定已由领域服务保存）
    session.add(
        HumanDecision(
            thread_id=thread.id,
            interrupt_id=thread.current_interrupt_id,
            actor_id=actor_id,
            action=action,
            comment=comment,
            edited_data=edited_data,
            payload_hash=payload_hash,
        )
    )
    await audit_service.audit(
        session,
        AuditAction.HUMAN_DECIDED.value,
        thread_id=thread.id,
        business_id=thread.business_id,
        actor_id=actor_id,
        target_type="approval" if intent == "leave" else "ticket",
        target_id=thread.business_id or str(thread.id),
        input_summary={
            "action": action,
            "comment": (comment or "")[:512],
            "edited": bool(edited_data),
        },
    )
    await session.flush()

    # 2. 恢复图
    try:
        result = await runtime.resume(thread.id, decision)
    except Exception as exc:
        if intent != "leave":
            raise
        from ..core.context import get_trace_id
        thread_id = thread.id
        await session.rollback()
        thread = await session.get(AgentThread, thread_id)
        await thread_repo.update_thread_status(session, thread, ThreadStatus.PAUSED.value,
            error_code=ErrorCode.DEPENDENCY_FAILED.value, error_msg="审批依赖结果未确认，请人工核对后恢复")
        await audit_service.audit(session, AuditAction.ERROR_OCCURRED.value,
            thread_id=thread.id, business_id=thread.business_id, actor_id=actor_id,
            result="fail", error_code=ErrorCode.DEPENDENCY_FAILED.value,
            input_summary={"step": "approval_write", "trace_id": get_trace_id()})
        await session.commit()
        raise AppException(ErrorCode.DEPENDENCY_FAILED, "审批写入未确认，任务已安全暂停", http_status=502) from exc
    new_interrupt = extract_interrupt(await runtime.get_state(thread.id))
    next_action = ("waiting_human" if new_interrupt else result.get("next_action"))
    status = map_next_action(next_action)
    if intent == "leave" and result_status == "waiting_human" and action == "approve" and new_interrupt is None:
        raise AppException(ErrorCode.INVALID_STATE, "下级审批中断尚未生成", http_status=409)
    await thread_repo.update_thread_status(session, thread, status, intent=thread.intent,
        current_interrupt_id=new_interrupt[0] if new_interrupt else None)
    thread.waiting_since = None
    if new_interrupt:
        from datetime import datetime, timezone
        thread.waiting_since = datetime.now(timezone.utc)
    await session.commit()
    return status, next_action
