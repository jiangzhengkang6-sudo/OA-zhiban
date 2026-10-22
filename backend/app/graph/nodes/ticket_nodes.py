"""
OA 智能体管理系统 - 工单子图节点。

实现工单字段抽取（LLM 结构化输出）、用户确认（HITL interrupt）与工单创建/合并
（写工具，幂等）。转人工时携带完整上下文（对话/检索结果/抽取字段）。
"""

import logging

from ...core.context import CurrentUser
from ...core.enums import AuditAction, HumanAction
from ...db.session import async_session_factory
from ...llm.base import LLMFactory
from ...llm.schemas import TicketExtraction
from ...models.ticket_context import TicketContext
from ...services import audit_service
from ...tools import ticket_tools
from ..graph_utils import interrupt_payload
from ..state import TicketState

logger = logging.getLogger("oa-agent")


async def ticket_extract(state: TicketState) -> dict:
    """抽取工单字段（类别/优先级/影响范围/摘要）。

    Args:
        state: 工单子图状态。

    Returns:
        dict: 更新后的 ticket_fields。
    """
    from ...core.config import get_settings
    if get_settings().oa_provider == 'builtin':
        from ...services.oa_ticket_graph_service import extract
        async with async_session_factory() as db:
            return await extract(db, state)
    confirmation = state.get("confirmation") or {}
    current = state.get("ticket_fields") or {}
    edited = confirmation.get("edited_data") or {} if confirmation.get("action") == "edit" else {}
    if edited:
        from ...services.ticket_draft_service import validate_draft_fields
        fields = {**current, **validate_draft_fields(edited)}
        extracted = (state.get('ticket_draft') or {}).get('extracted_fields') or current
    else:
        llm = LLMFactory.get_llm()
        question = _extract_question(state)
        extraction = await llm.structured(
            [{"role": "user", "content": question or "请描述你的问题"}],
            TicketExtraction,
        )
        extracted = extraction.model_dump()
        from ...schemas.ticket_draft import ALLOWED_DRAFT_FIELDS
        fields = {key: value for key, value in extracted.items() if key in ALLOWED_DRAFT_FIELDS}
    from ...services.ticket_draft_service import upsert_draft
    async with async_session_factory() as db:
        draft = await upsert_draft(db, tenant_id=state["tenant_id"], thread_id=_uuid(state),
            user_id=state["user_id"], fields=fields, extracted_fields=extracted)
        await db.commit()
    return {"ticket_fields": fields, "ticket_draft": {"thread_id": str(draft.thread_id),
        "fields": draft.fields, "extracted_fields": draft.extracted_fields, "status": draft.status}}


def ticket_confirm(state: TicketState) -> dict:
    """用户确认工单草稿（HITL interrupt）。

    Args:
        state: 工单子图状态。

    Returns:
        dict: 中断恢复后的 confirmation。
    """
    from langgraph.types import interrupt

    payload = interrupt_payload(state)
    payload.update(
        {
            "type": "ticket_confirm",
            "ticket_fields": state.get("ticket_draft", {}).get("fields") or state.get("ticket_fields"),
        }
    )
    decision = interrupt(payload)
    return {"confirmation": decision}


async def create_ticket(state: TicketState) -> dict:
    """创建或合并工单（写操作，幂等键 = thread_id）。

    Args:
        state: 工单子图状态。

    Returns:
        dict: 更新后的 ticket/next_action。
    """
    from ...core.config import get_settings
    if get_settings().oa_provider == 'builtin':
        from ...services.oa_ticket_graph_service import reconciled_result
        async with async_session_factory() as db:
            return await reconciled_result(db, state)
    fields = state.get("ticket_draft", {}).get("fields") or state.get("ticket_fields") or {}
    confirmation = state.get("confirmation") or {}
    thread_id = str(state["thread_id"])
    async with async_session_factory() as db:
        from ...services.ticket_draft_service import get_draft
        from ...services import ticket_service
        from ...schemas.ticket import TicketCreateRequest
        persisted_draft = await get_draft(db, _uuid(state))
        if persisted_draft is not None:
            fields = persisted_draft.fields or fields
            persisted_draft.status = "CONFIRMED"
            persisted_draft.confirmation_key = thread_id
        actor = CurrentUser(user_id=state["user_id"], tenant_id=state["tenant_id"], roles=["employee"])
        payload = TicketCreateRequest(
            idempotency_key=thread_id, thread_id=_uuid(state),
            category=fields.get("category", "其他"), priority=fields.get("priority", "medium"),
            summary=fields.get("summary", ""),
            context={"messages": (state.get("messages") or [])[-5:], "impact": fields.get("impact", "个人")},
        )
        result = await ticket_service.create_or_review(db, actor, payload)
        ticket_id = result.get("ticket_id", "")
        if result.get("status") == "DUPLICATE_REVIEW":
            await db.commit()
            return {"ticket": result, "next_action": "human"}
        # 持久化工单上下文快照
        db.add(
            TicketContext(
                ticket_id=ticket_id,
                thread_id=_uuid(state),
                category=payload.category,
                priority=payload.priority,
                impact=payload.context.get("impact", "个人"),
                summary=payload.summary,
                extracted_fields=fields,
                status="open",
            )
        )
        await audit_service.audit(
            db,
            AuditAction.BUSINESS_WRITE.value,
            thread_id=_uuid(state),
            business_id=ticket_id,
            target_type="ticket",
            target_id=ticket_id,
        )
        await audit_service.audit(db, AuditAction.HUMAN_DECIDED.value,
            thread_id=_uuid(state), actor_id=state["user_id"], target_type="ticket_draft",
            target_id=thread_id, input_summary={"action": "confirm", "category": payload.category,
                "priority": payload.priority, "impact": payload.context.get("impact", "个人"),
                "summary": payload.summary[:256],
                "changed_fields": []})
        await db.commit()
    return {"ticket": result, "next_action": "human"}


async def ticket_human(state: TicketState) -> dict:
    """转人工队列节点（工单已创建或直接转人工）。

    Args:
        state: 工单子图状态。

    Returns:
        dict: 状态片段。
    """
    from ...core.config import get_settings
    if get_settings().oa_provider == 'builtin':
        from ...services.oa_graph_service import actor_for_thread
        async with async_session_factory() as db:
            await actor_for_thread(db, state)
        return {'next_action': 'human'}
    if (state.get("ticket") or {}).get("ticket_id"):
        return {"next_action": "human"}
    from ...services.handoff_service import ensure_handoff
    async with async_session_factory() as db:
        item = await ensure_handoff(db, tenant_id=state["tenant_id"], thread_id=_uuid(state),
            user_id=state["user_id"], scene="ticket", reason_code="TICKET_HUMAN",
            context={"summary": (state.get("ticket_fields") or {}).get("summary", ""),
                     "messages": state.get("messages") or [],
                     "extracted_fields": state.get("ticket_fields") or {}})
        await db.commit()
    return {"next_action": "human", "handoff": {"queue_item_id": str(item.id), "reason_code": "TICKET_HUMAN"}}


def _extract_question(state: TicketState) -> str:
    """提取用户问题文本。

    Args:
        state: 图状态。

    Returns:
        str: 用户问题。
    """
    messages = state.get("messages") or []
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""


def _uuid(state: TicketState):
    """从状态提取 thread_id 的 UUID。

    Args:
        state: 图状态。

    Returns:
        UUID: 会话 ID。
    """
    from uuid import UUID

    raw = state.get("thread_id")
    return UUID(str(raw)) if raw else None


async def ticket_cancelled(state: TicketState) -> dict:
    """用户取消工单创建节点。

    Args:
        state: 工单子图状态。

    Returns:
        dict: 状态片段。
    """
    return {"next_action": "cancelled"}
