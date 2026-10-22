"""
OA 智能体管理系统 - 通用图节点。

包含 SuperAgent 顶层的 load_context（加载上下文与开关，降级短路）、classify_intent
（LLM 意图分类）、degrade（降级审计）与 audit_tail（收尾审计）。
"""

import logging
from typing import Optional

from ...adapters.factory import get_adapter
from ...core.enums import AuditAction
from ...db.session import async_session_factory
from ...llm.base import LLMFactory
from ...llm.schemas import IntentClassification
from ...services import audit_service, policy_service
from ..state import AgentState

logger = logging.getLogger("oa-agent")


async def load_context(state: AgentState) -> dict:
    """加载用户上下文、权限快照与场景开关；开关关闭则降级短路。

    Args:
        state: 图状态。

    Returns:
        dict: 更新后的状态片段（permissions/policy/next_action/error）。
    """
    from ...core.config import get_settings
    if get_settings().oa_provider == 'builtin':
        from ...adapters.builtin_gateway import BuiltinGateway
        from ...adapters.gateway import BridgeContext
        from ...services.oa_graph_service import actor_for_thread
        async with async_session_factory() as db:
            actor = await actor_for_thread(db, state)
            gateway = BuiltinGateway(BridgeContext(actor=actor, session=db, trace_id=state.get('trace_id')))
            context = await gateway.get_user_context()
            enabled = await policy_service.is_scene_enabled(db, state['scene'], actor.user_id,
                context['dept_id'], tenant_id=actor.tenant_id)
            thresholds = await policy_service.get_thresholds(db, state['scene'], user_id=actor.user_id,
                dept_id=context['dept_id'], tenant_id=actor.tenant_id)
            await audit_service.audit(db, AuditAction.SESSION_CREATED.value, thread_id=_tid(state),
                target_type='knowledge' if state['scene'] == 'faq' else 'thread', target_id=state['thread_id'])
            await db.commit()
        update = dict(tenant_id=actor.tenant_id, permissions=dict(roles=context['roles'],
            dept_id=context['dept_id'], data_scope=context['data_scope']), policy=dict(enabled=enabled, thresholds=thresholds))
        if not enabled:
            update.update(next_action='degraded', error=dict(code='DEGRADED', msg='智能路径已关闭，请转人工处理'))
        else:
            update.update(next_action='classify', error=None)
        return update
    adapter = get_adapter()
    user_id = state["user_id"]
    scene = state["scene"]

    ctx = adapter.get_user_context(user_id)
    if ctx is None:
        # 上下文加载失败：终止并告警（PRD 5.2 load_context 失败处理）
        return {
            "next_action": "paused",
            "error": {"code": "CONTEXT_FAILED", "msg": "用户上下文加载失败"},
        }

    async with async_session_factory() as db:
        enabled = await policy_service.is_scene_enabled(
            db, scene, user_id, ctx.dept_id, tenant_id=ctx.tenant_id
        )
        thresholds = await policy_service.get_thresholds(
            db, scene, user_id=user_id, dept_id=ctx.dept_id, tenant_id=ctx.tenant_id
        )
        await audit_service.audit(
            db,
            AuditAction.SESSION_CREATED.value,
            thread_id=_tid(state),
            business_id=state.get("business_id"),
        )

    update: dict = {
        "tenant_id": ctx.tenant_id,
        "permissions": {
            "roles": ctx.roles,
            "dept_id": ctx.dept_id,
            "data_scope": ctx.data_scope,
        },
        "policy": {"enabled": enabled, "thresholds": thresholds},
    }
    if not enabled:
        update["next_action"] = "degraded"
        update["error"] = {"code": "DEGRADED", "msg": "智能路径已关闭，请走原 OA"}
    return update


async def classify_intent(state: AgentState) -> dict:
    """调用 LLM 识别意图并做置信度阈值判断。

    Args:
        state: 图状态。

    Returns:
        dict: 更新后的 intent/intent_confidence/next_action。
    """
    from ...core.config import get_settings
    formal = get_settings().oa_provider == 'builtin'
    thresholds = state['policy']['thresholds']
    if formal:
        from ...services.oa_graph_service import scene_context
        async with async_session_factory() as db:
            _, thresholds = await scene_context(db, state, tool='get_user_context')
    llm = LLMFactory.get_llm()
    question = _last_user_text(state.get("messages") or [])
    result = await llm.structured(
        [{"role": "user", "content": question or state.get("scene", "")}],
        IntentClassification,
    )
    if formal:
        async with async_session_factory() as db:
            _, thresholds = await scene_context(db, state, tool='get_user_context')
    threshold = float(thresholds.get("intent_confidence", 0.6))
    intent = result.intent if result.confidence >= threshold else "unknown"
    # 未知意图统一转人工（由工单子图兜底）
    if intent == "unknown":
        intent = "human"
    return {"intent": intent, "intent_confidence": result.confidence}


async def degrade(state: AgentState) -> dict:
    """降级节点：写入降级审计并置暂停态。

    Args:
        state: 图状态。

    Returns:
        dict: 更新后的状态片段。
    """
    async with async_session_factory() as db:
        from ...core.config import get_settings
        formal = get_settings().oa_provider == 'builtin'
        if formal:
            from ...services.oa_graph_service import actor_for_thread
            await actor_for_thread(db, state)
        await audit_service.audit(
            db,
            AuditAction.DEGRADED.value,
            thread_id=_tid(state),
            business_id=state.get("business_id"),
            result="fail",
            error_code="DEGRADED",
            target_type=('knowledge' if state['scene'] == 'faq' else 'thread') if formal else None,
            target_id=state['thread_id'] if formal else None,
        )
        await db.commit()
    return {"next_action": "degraded"}


async def audit_tail(state: AgentState) -> dict:
    """收尾节点：记录意图路由结果审计。

    Args:
        state: 图状态。

    Returns:
        dict: 空更新（审计副作用）。
    """
    async with async_session_factory() as db:
        from ...core.config import get_settings
        formal = get_settings().oa_provider == 'builtin'
        if formal:
            from ...services.oa_graph_service import actor_for_thread
            await actor_for_thread(db, state)
        await audit_service.audit(
            db,
            AuditAction.INTENT_ROUTED.value,
            thread_id=_tid(state),
            business_id=state.get("business_id"),
            input_summary={"intent": state.get("intent"), "confidence": state.get("intent_confidence")},
            target_type=('knowledge' if state['scene'] == 'faq' else 'thread') if formal else None,
            target_id=state['thread_id'] if formal else None,
        )
        await db.commit()
    return {}


def _tid(state: AgentState) -> Optional[str]:
    """从状态提取 thread_id。

    Args:
        state: 图状态。

    Returns:
        Optional[str]: thread_id。
    """
    return state.get("thread_id")


def _last_user_text(messages: list[dict]) -> str:
    """取最后一条用户消息文本。

    Args:
        messages: 消息列表。

    Returns:
        str: 用户消息内容。
    """
    for m in reversed(messages):
        if m.get("role") == "user":
            return str(m.get("content", ""))
    return ""
