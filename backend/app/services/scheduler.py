"""
OA 智能体管理系统 - 超时催办/升级后台调度。

独立于 LangGraph 图的 asyncio 后台任务，周期性扫描 WAITING_HUMAN 会话：
超过催办阈值发送催办通知，超过升级阈值升级（转上级/代理人/人工队列）。
"""

import asyncio
import logging
from datetime import datetime, timezone

from ..adapters.factory import get_adapter
from ..core.config import get_settings
from ..core.enums import AuditAction, ErrorCode
from ..db.session import async_session_factory
from ..repositories import thread_repo
from ..services import audit_service, policy_service
from ..services.approval_service import active_node

logger = logging.getLogger("oa-agent")


async def _current_node_locked(db, thread, node, stage: str) -> bool:
    """Use the same instance lock order as approval_service.record_decision."""
    from ..models.approval_instance import ApprovalInstance
    from sqlalchemy import select
    instance = (await db.scalars(select(ApprovalInstance).where(
        ApprovalInstance.id == node.instance_id).with_for_update())).one()
    await db.refresh(node)
    await db.refresh(thread)
    if instance.status != "ACTIVE" or node.status != "ACTIVE" or thread.status != "WAITING_HUMAN":
        return False
    if stage == "nudge" and node.last_nudge_at is not None:
        return False
    if stage == "escalate" and node.escalated_at is not None:
        return False
    return True


async def run_scheduler(stop_event: asyncio.Event) -> None:
    """调度主循环：周期性扫描并处理超时任务。

    Args:
        stop_event: 停止信号（应用关闭时 set）。
    """
    settings = get_settings()
    interval = settings.scheduler_interval_seconds
    logger.info("催办升级调度器已启动（间隔 %s 秒）", interval)

    while not stop_event.is_set():
        try:
            if settings.auth_provider == 'builtin':
                from .oa_workflow_scheduler import scan
                async with async_session_factory() as formal_db:
                    report = await scan(formal_db)
                    await formal_db.commit()
                    if report['errors']:
                        logger.warning('正式流程扫描部分失败: %s', report['errors'])
            elif settings.ai_enabled:
                await _tick()
        except Exception as exc:  # 单次失败不终止循环
            logger.warning("调度器执行失败: %s", exc)
        try:
            if settings.auth_provider == 'builtin' or (
                settings.auth_provider == 'mock' and settings.ai_enabled
            ):
                from .work_task_scheduler import scan_overdue
                async with async_session_factory() as task_db:
                    await scan_overdue(task_db)
                    await task_db.commit()
        except Exception as exc:
            logger.warning("业务任务提醒扫描失败: %s", exc)
        if settings.auth_provider == 'builtin':
            try:
                from .oa_notification_service import dispatch
                async with async_session_factory() as notification_db:
                    await dispatch(notification_db)
                    await notification_db.commit()
            except Exception:
                logger.warning('正式通知入箱失败，保留队列等待重试')
            try:
                from .oa_notification_worker import run_once
                await run_once(async_session_factory)
            except Exception:
                logger.warning('正式邮件扫描失败，保留渠道状态等待核对')
            try:
                from .oa_notification_worker import run_once
                await run_once(async_session_factory,channel='wecom')
            except Exception:
                logger.warning('正式企业微信扫描失败，保留渠道状态等待核对')
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def _tick() -> None:
    """单次扫描：处理超时的 WAITING_HUMAN 会话。

    Raises:
        不抛出：内部异常单独捕获。
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if settings.auth_provider != 'mock':
        return
    adapter = get_adapter()

    async with async_session_factory() as db:
        from ..models.agent_thread import AgentThread
        from sqlalchemy import select

        stmt = select(AgentThread).where(
            AgentThread.status == "WAITING_HUMAN"
        )
        result = await db.execute(stmt)
        threads = list(result.scalars().all())

        for thread in threads:
            try:
                async with db.begin_nested():
                    await _process_waiting_thread(db, adapter, thread, settings, now)
            except Exception as exc:
                logger.warning("处理等待任务 %s 失败，未重发不确定通知: %s", thread.id, exc)
                if thread.scene == "leave":
                    from ..models.idempotency_record import IdempotencyRecord
                    from ..models.approval_instance import ApprovalInstance
                    node = await active_node(db, thread.id)
                    if node:
                        ledger = (await db.scalars(select(IdempotencyRecord).where(
                            IdempotencyRecord.resource_type == "approval_nudge",
                            IdempotencyRecord.idempotency_key == f"nudge-{node.id}"
                        ))).one_or_none()
                        if ledger and ledger.status in {"PENDING", "UNKNOWN"} and await _current_node_locked(db, thread, node, "nudge"):
                            instance = await db.get(ApprovalInstance, node.instance_id)
                            instance.status = "PAUSED"
                            thread.status = "PAUSED"
                            thread.error_code = ErrorCode.DEPENDENCY_FAILED.value
                            thread.error_msg = "催办通知结果无法确认，审批已暂停，请人工核对"
                await audit_service.audit(db, AuditAction.ERROR_OCCURRED.value,
                    thread_id=thread.id, business_id=thread.business_id, actor_id="system",
                    error_code=ErrorCode.DEPENDENCY_FAILED.value, input_summary={"step": "scheduler"})

        await db.commit()


async def _process_waiting_thread(db, adapter, thread, settings, now):
    node = await active_node(db, thread.id) if thread.scene == "leave" else None
    if thread.scene == "leave" and node is None:
        from ..graph.graph_service import runtime, extract_interrupt
        from ..services.approval_service import adopt_legacy_pending
        if thread.current_interrupt_id and runtime.ready:
            snapshot = await runtime.get_state(thread.id)
            pending = extract_interrupt(snapshot)
            if pending and pending[0] == thread.current_interrupt_id:
                await adopt_legacy_pending(db, thread, pending[1])
                await db.flush()
                node = await active_node(db, thread.id)
        if node is None:
            return
    waiting_since = node.waiting_since if node else thread.waiting_since
    if waiting_since is None:
        return
    elapsed = (now - waiting_since).total_seconds()
    thresholds = await policy_service.get_thresholds(
        db, thread.scene, user_id=thread.user_id, tenant_id=thread.tenant_id
    )
    nudge_after = int(thresholds.get("nudge_after_seconds", settings.nudge_after_seconds))
    escalate_after = int(thresholds.get("escalate_after_seconds", settings.escalate_after_seconds))
    if elapsed >= nudge_after and (node.last_nudge_at if node else thread.last_nudge_at) is None:
        await _nudge(db, adapter, thread, node)
        return
    if elapsed >= escalate_after and (node.escalated_at if node else thread.escalated_at) is None:
        await _escalate(db, adapter, thread, node)


async def _nudge(db, adapter, thread, node=None) -> None:
    """发送催办通知并记录催办时间。

    Args:
        db: 数据库会话。
        adapter: OA 适配器。
        thread: 会话记录。
    """
    from ..tools import notify_tools
    from ..schemas.command import CommandEnvelope
    from ..models.idempotency_record import IdempotencyRecord
    from ..services.idempotency_service import claim, complete
    from uuid import uuid4

    if node and not await _current_node_locked(db, thread, node, "nudge"):
        return

    recipient = node.approver_id if node else thread.user_id
    key = f"nudge-{node.id if node else thread.id}"
    body = f"您的申请 {thread.business_id or thread.id} 正在等待审批，请及时处理。"
    envelope = CommandEnvelope(command_id=uuid4(), idempotency_key=key,
        actor_id="system", tenant_id=thread.tenant_id, resource_type="approval_nudge",
        resource_id=str(node.id if node else thread.id), trace_id=str(uuid4()),
        payload={"user_id": recipient, "body": body, "title": "审批待办催办"})
    # Separate transaction makes the claim durable before the external send;
    # the held instance lock prevents other schedulers deciding for this node.
    from ..db.session import async_session_factory
    async with async_session_factory() as ledger:
        record, is_new = await claim(ledger, envelope)
        await ledger.commit()
        if is_new:
            try:
                result = await notify_tools.notify_user(adapter, user_id=recipient,
                    title="审批待办催办", body=body, business_id=thread.business_id or "",
                    idempotency_key=key)
            except Exception:
                uncertain = await ledger.get(IdempotencyRecord, record.id)
                uncertain.status = "UNKNOWN"
                await ledger.commit()
                raise
            if not result.get("delivered") or not result.get("success"):
                uncertain = await ledger.get(IdempotencyRecord, record.id)
                uncertain.status = "UNKNOWN"
                await ledger.commit()
                raise RuntimeError("催办通知未确认送达，不能标记节点已催办")
            pending = await ledger.get(IdempotencyRecord, record.id)
            await complete(ledger, pending, result)
            pending.external_request_id = result.get("request_id")
            await ledger.commit()
    if node:
        node.last_nudge_at = datetime.now(timezone.utc)
    else:
        thread.last_nudge_at = datetime.now(timezone.utc)
    await audit_service.audit(
        db,
        AuditAction.NOTIFICATION_SENT.value,
        thread_id=thread.id,
        business_id=thread.business_id,
        actor_id="system",
        input_summary={"type": "nudge", "node_id": str(node.id) if node else None},
    )
    logger.info("已催办会话 %s", thread.id)


async def _escalate(db, adapter, thread, node=None) -> None:
    """超时升级：置 ESCALATED 并通知上级/转人工。

    Args:
        db: 数据库会话。
        adapter: OA 适配器。
        thread: 会话记录。
    """
    from ..models.human_decision import HumanDecision
    from ..models.approval_node import ApprovalNode
    from ..models.approval_instance import ApprovalInstance
    from sqlalchemy import select

    if node:
        if not await _current_node_locked(db, thread, node, "escalate"):
            return
        node.escalated_at = datetime.now(timezone.utc)
        # The ordered route's next configured approver is the only safe
        # escalation target. Never invent a new approver from graph state.
        next_node = (await db.scalars(select(ApprovalNode).where(
            ApprovalNode.instance_id == node.instance_id,
            ApprovalNode.node_order > node.node_order,
            ApprovalNode.status == "PENDING",
        ).order_by(ApprovalNode.node_order).limit(1).with_for_update())).one_or_none()
        node.status = "ESCALATED"
        await db.flush()  # retire old active row before activating another
        if next_node:
            next_node.status = "ACTIVE"
            next_node.waiting_since = datetime.now(timezone.utc)
            thread.status = "WAITING_HUMAN"
        else:
            instance = await db.get(ApprovalInstance, node.instance_id)
            instance.status = "PAUSED"
            thread.status = "PAUSED"
            thread.error_code = "ROUTE_CONFLICT"
            thread.error_msg = "当前审批节点超时且无已配置升级处理人，请人工接管"
    else:
        thread.escalated_at = datetime.now(timezone.utc)
        thread.status = "ESCALATED"
    # 记录系统升级决定（满足高影响动作审计语义）
    db.add(
        HumanDecision(
            thread_id=thread.id,
            interrupt_id=thread.current_interrupt_id,
            actor_id="system",
            action="escalate",
            comment="审批超时，自动升级",
        )
    )
    await audit_service.audit(
        db,
        AuditAction.HUMAN_DECIDED.value,
        thread_id=thread.id,
        business_id=thread.business_id,
        actor_id="system",
        input_summary={"action": "escalate", "node_id": str(node.id) if node else None,
                       "escalated_to": next_node.approver_id if node and next_node else None},
    )
    logger.info("已升级会话 %s", thread.id)
