"""
OA 智能体管理系统 - FAQ 问答子图节点。

实现 faq_retrieve（权限过滤检索 + 置信度判断）与 faq_answer（基于检索证据回答并引用
来源）。低置信度/未命中/检索失败时转人工兜底，不猜测。
"""

import logging

from ...core.config import get_settings
from ...core.errors import AppException
from ...core.enums import AuditAction
from ...db.session import async_session_factory
from ...llm.base import LLMFactory
from ...services import audit_service
from ...tools import knowledge_tools
from ..state import FaqState

logger = logging.getLogger("oa-agent")


async def _formal_evidence(db, state, chunks):
    from ...services.oa_graph_service import faq_context, canonical_chunks
    actor, thresholds = await faq_context(db, state)
    return await canonical_chunks(db, actor, chunks), float(thresholds.get('faq_answer', 0.65))


async def faq_retrieve(state: FaqState) -> dict:
    """权限过滤知识检索并判断是否命中。

    Args:
        state: FAQ 子图状态。

    Returns:
        dict: 更新后的 faq_chunks/next_action。
    """
    question = _extract_question(state)
    dept_id = (state.get("permissions") or {}).get("dept_id", "")
    permission_tags = [dept_id] if dept_id else []
    threshold = float(state["policy"]["thresholds"].get("faq_answer", 0.65))

    async with async_session_factory() as db:
        try:
            if get_settings().oa_provider == 'builtin':
                await _formal_evidence(db, state, [])
            chunks = await knowledge_tools.search_knowledge(
                db, query=question, permission_tags=permission_tags
            )
            if get_settings().oa_provider == 'builtin':
                chunks, threshold = await _formal_evidence(db, state, chunks)
            await audit_service.audit(
                db,
                AuditAction.KNOWLEDGE_RETRIEVED.value,
                thread_id=_uuid(state),
                business_id=state.get("business_id"),
                input_summary={"query": question[:100], "hits": len(chunks)},
                target_type='knowledge' if get_settings().oa_provider == 'builtin' else None,
                target_id=state['thread_id'] if get_settings().oa_provider == 'builtin' else None,
            )
            await db.commit()
        except Exception as exc:
            logger.warning("知识检索失败: %s", exc)
            return {"faq_chunks": [], "answer": None, "next_action": "human"}

    if not chunks:
        return {"faq_chunks": [], "answer": None, "next_action": "human"}

    top_sim = float(chunks[0].get("similarity", 0))
    if top_sim < threshold:
        return {"faq_chunks": chunks, "answer": None, "next_action": "human"}

    return {"faq_chunks": chunks, "next_action": "answer"}


async def faq_answer(state: FaqState) -> dict:
    """基于检索证据生成带来源回答。

    Args:
        state: FAQ 子图状态。

    Returns:
        dict: 更新后的 answer/next_action。
    """
    chunks = state.get("faq_chunks") or []
    formal = get_settings().oa_provider == 'builtin'
    if formal:
        async with async_session_factory() as db:
            try:
                chunks, threshold = await _formal_evidence(db, state, chunks)
            except AppException as error:
                if error.http_status != 403:
                    raise
                return {'faq_chunks': [], 'answer': None, 'next_action': 'human'}
        if not chunks or float(chunks[0].get('similarity', 0)) < threshold:
            return {'faq_chunks': [], 'answer': None, 'next_action': 'human'}
    sources = [
        {
            "document_id": c.get("document_id"),
            "title": c.get("title"),
            "source_location": c.get("source_location"),
            "similarity": c.get("similarity"),
            **({key: c[key] for key in ('chunk_id', 'version_id', 'source_id', 'content_hash')} if formal else {}),
        }
        for c in chunks
    ]
    # 拼接证据生成回答（Mock 确定性；真实提供方由 LLM 生成）
    context = "\n".join(c.get("content", "") for c in chunks)
    llm = LLMFactory.get_llm()
    question = _extract_question(state)
    if get_settings().llm_provider != "mock":
        answer_text = await llm.chat(
            [
                {"role": "system", "content": "仅依据给定知识片段回答，并保持可追溯来源。"},
                {"role": "user", "content": f"知识片段：{context}\n问题：{question}"},
            ]
        )
    else:
        answer_text = context if context else f"已为您检索到 {len(chunks)} 条相关内容。"

    confidence = float(chunks[0].get("similarity", 0)) if chunks else 0.0
    answer = {
        "answer": answer_text,
        "sources": sources,
        "confidence": confidence,
    }
    async with async_session_factory() as db:
        if formal:
            try:
                chunks, threshold = await _formal_evidence(db, state, chunks)
            except AppException as error:
                if error.http_status != 403:
                    raise
                return {'faq_chunks': [], 'answer': None, 'next_action': 'human'}
            if not chunks or float(chunks[0].get('similarity', 0)) < threshold:
                return {'faq_chunks': [], 'answer': None, 'next_action': 'human'}
        await audit_service.audit(
            db,
            AuditAction.MODEL_ANSWERED.value,
            thread_id=_uuid(state),
            business_id=state.get("business_id"),
            input_summary={"confidence": confidence, "sources": len(sources)},
            target_type='knowledge' if formal else None,
            target_id=state['thread_id'] if formal else None,
        )
        await db.commit()
    return {"answer": answer, "faq_chunks": chunks, "handoff": None, "next_action": "answered"}


def _extract_question(state: FaqState) -> str:
    """提取用户问题文本。

    Args:
        state: FAQ 子图状态。

    Returns:
        str: 用户问题。
    """
    q = state.get("question") or ""
    if q:
        return q
    messages = state.get("messages") or []
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return q


def _uuid(state: FaqState):
    """从状态提取 thread_id 的 UUID。

    Args:
        state: 图状态。

    Returns:
        UUID: 会话 ID。
    """
    from uuid import UUID

    raw = state.get("thread_id")
    return UUID(str(raw)) if raw else None


async def faq_to_human(state: FaqState) -> dict:
    """FAQ 未命中转人工兜底节点。

    Args:
        state: FAQ 子图状态。

    Returns:
        dict: 更新后的状态片段（转人工）。
    """
    from ...services.handoff_service import ensure_handoff
    reason = "FAQ_HUMAN_REQUEST" if state.get("intent") == "human" else "FAQ_UNCERTAIN"
    async with async_session_factory() as db:
        sources = state.get('faq_chunks') or []
        if get_settings().oa_provider == 'builtin':
            from ...services.oa_graph_service import actor_for_thread
            await actor_for_thread(db, state)
            sources = []
        item = await ensure_handoff(db, tenant_id=state["tenant_id"], thread_id=_uuid(state),
            user_id=state["user_id"], scene="faq", reason_code=reason,
            context={"summary": _extract_question(state), "messages": state.get("messages") or [],
                     "faq_sources": sources})
        await db.commit()
    return {"answer": None, "next_action": "human", "handoff": {"queue_item_id": str(item.id), "reason_code": reason}}
