"""
OA 智能体管理系统 - 请假审批子图节点。

实现预检、路由、审批门（HITL interrupt）、审批执行、驳回摘要与通知节点。
写工具严格在 HITL 通过后调用，且幂等（幂等键 = business_id）。
"""

import logging
from sqlalchemy import select

from ...adapters.factory import get_adapter
from ...adapters.oa_adapter import ApprovalCommand, ApprovalNode, LeaveCase, LeaveEditCommand
from ...core.enums import AuditAction, ErrorCode, HumanAction, PrecheckItem, ThreadStatus
from ...db.session import async_session_factory
from ...llm.base import LLMFactory
from ...llm.schemas import RejectSummary
from ...models.precheck_result import PrecheckResult
from ...repositories import precheck_repo
from ...services import audit_service
from ...services import approval_service
from ...services.idempotency_service import claim, complete
from ...schemas.command import CommandEnvelope
from ...models.idempotency_record import IdempotencyRecord
from ...tools.base import call_tool
from ...core.context import CurrentUser
from ...services.authorization_service import authorize_tool
from ...services import policy_service
from ...tools import leave_tools, notify_tools, approval_tools
from ..state import LeaveState
from ..graph_utils import interrupt_payload

logger = logging.getLogger("oa-agent")


async def precheck(state: LeaveState) -> dict:
    """材料预检：字段/附件/余额/时间冲突四项确定性校验。

    Args:
        state: 请假子图状态。

    Returns:
        dict: 更新后的 precheck/next_action/error/form_snapshot。
    """
    adapter = get_adapter()
    business_id = state.get("business_id")
    user_id = state["user_id"]

    if not business_id:
        # 无业务单据号（自然语言请假暂不启用，MVP 请假必须来自 OA 提交）
        return _paused("CASE_NOT_FOUND", "缺少请假单据号，请从 OA 提交请假单")

    try:
        case = adapter.get_leave_case(business_id)
    except TimeoutError as exc:
        return _paused("DEPENDENCY_FAILED", f"预检依赖超时：{exc}")
    except Exception as exc:  # 依赖异常：不自动通过
        return _paused("DEPENDENCY_FAILED", f"预检依赖异常：{exc}")

    if case is None:
        return _paused("CASE_NOT_FOUND", "请假单不存在")
    if case.user_id != user_id:
        return _paused("CASE_NOT_FOUND", "无法读取当前申请人的请假材料")

    # 四项检查
    try:
        results = await leave_tools.validate_leave_form(adapter, case)
        days = leave_tools.compute_days(case)
        balance = adapter.get_leave_balance(user_id, case.leave_type).model_dump()
        results.append(leave_tools.check_balance(balance, case.leave_type, days))
        results.append(leave_tools.check_conflict(case))
        rule_version = adapter.get_field_dict().get("rule_version", "v1")
    except Exception as exc:
        logger.warning("请假预检依赖失败: %s", exc)
        return _paused("DEPENDENCY_FAILED", "预检依赖暂不可用，审批已安全暂停")
    all_pass = all(r["result"] == "pass" for r in results)

    # 持久化预检结果
    async with async_session_factory() as db:
        for r in results:
            await precheck_repo.add_result(
                db,
                thread_id=_uuid(state),
                business_id=business_id,
                rule_version=rule_version,
                item=r["item"],
                result=r["result"],
                reason=r.get("reason"),
                suggestion=r.get("suggestion"),
            )
        await audit_service.audit(
            db,
            AuditAction.PRECHECK_RESULT.value,
            thread_id=_uuid(state),
            business_id=business_id,
            input_summary={"passed": all_pass, "rule_version": rule_version},
        )
        await db.commit()

    precheck_summary = {
        "results": results,
        "passed": all_pass,
        "rule_version": rule_version,
    }
    if all_pass:
        return {
            "precheck": precheck_summary,
            "form_snapshot": case.model_dump(),
            "next_action": "route",
        }
    return {
        "precheck": precheck_summary,
        "next_action": "needs_fix",
        "error": {"code": "NEEDS_FIX", "msg": "预检未通过，请补充材料"},
    }


async def route(state: LeaveState) -> dict:
    """审批路由：读取 OA 组织/代理数据生成审批链建议。

    Args:
        state: 请假子图状态。

    Returns:
        dict: 更新后的 approval_route/next_action。
    """
    from ...adapters.oa_adapter import LeaveCase

    adapter = get_adapter()
    business_id = state["business_id"]
    user_id = state["user_id"]
    case = LeaveCase(**state["form_snapshot"])

    try:
        route = await leave_tools.get_approval_route(adapter, user_id, case)
    except TimeoutError as exc:
        return _paused("DEPENDENCY_FAILED", f"路由依赖超时：{exc}")
    except Exception as exc:
        logger.warning("组织路由不可判定: %s", exc)
        return _paused("DEPENDENCY_FAILED", "组织路由暂不可用，审批已安全暂停")

    if route.get("conflict"):
        return _paused("ROUTE_CONFLICT", "组织数据冲突，无法确定审批人")

    async with async_session_factory() as db:
        try:
            await approval_service.ensure_instance(db, _uuid(state), state["tenant_id"],
                                                   business_id, route)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.warning("创建审批实例失败: %s", exc)
            return _paused("DEPENDENCY_FAILED", "审批实例写入失败，请稍后重试")

    return {"approval_route": route, "next_action": "waiting_human"}


async def approval_gate(state: LeaveState) -> dict:
    """HITL 审批门：中断等待 approve/edit/reject。

    Args:
        state: 请假子图状态。

    Returns:
        dict: 中断恢复后的 human_decision。
    """
    payload = interrupt_payload(state)
    payload.update(
        {
            "type": "approval",
            "precheck": state.get("precheck"),
            "approval_route": state.get("approval_route"),
            "form_snapshot": state.get("form_snapshot"),
        }
    )
    from langgraph.types import interrupt

    decision = interrupt(payload)
    # The checkpoint is orchestration only. Never advance it on an unrecorded
    # or unauthorized human decision (including direct runtime callers).
    async with async_session_factory() as db:
        result = await approval_service.record_decision(
            db, _uuid(state), decision.get("actor_id", ""), decision.get("action", ""),
            decision.get("comment", ""), decision.get("edited_data"),
            decision.get("idempotency_key", ""),
        )
        await db.commit()
    return {"human_decision": {**decision, "result_status": result}}


async def execute_approval(state: LeaveState) -> dict:
    """执行审批写操作（仅 HITL 通过后调用，幂等）。

    Args:
        state: 请假子图状态。

    Returns:
        dict: 更新后的 next_action。
    """
    adapter = get_adapter()
    decision = state.get("human_decision") or {}
    action = decision.get("action")
    if action != HumanAction.APPROVE.value:
        return {"next_action": "rejected"}
    if decision.get("result_status") != "pending_write":
        return {"next_action": "waiting_human"}

    business_id = state["business_id"]
    # The checkpoint is not authoritative: a form edited outside this flow
    # must go through precheck again before any final external write or claim.
    approval_service.verify_authoritative_form(
        business_id, state["user_id"], state.get("form_snapshot"))
    route = state.get("approval_route") or {}
    nodes = [
        ApprovalNode(**n) for n in route.get("nodes", [])
    ]
    command = ApprovalCommand(
        business_id=business_id,
        idempotency_key=f"approval-{_uuid(state)}",
        action="approve",
        actor_id=decision.get("actor_id", state["user_id"]),
        comment=decision.get("comment", ""),
        route=nodes,
    )
    from uuid import uuid4
    envelope = CommandEnvelope(command_id=uuid4(), idempotency_key=command.idempotency_key,
        actor_id=command.actor_id, tenant_id=state["tenant_id"],
        resource_type="approval_write", resource_id=business_id,
        trace_id=state.get("trace_id") or str(uuid4()),
        payload={"business_id": business_id, "action": command.action,
                 "version": 1, "actor_id": command.actor_id})
    async with async_session_factory() as db:
        def current_approver():
            identity = adapter.get_user_context(command.actor_id)
            if identity is None or identity.tenant_id != state["tenant_id"] or "approver" not in identity.roles:
                raise RuntimeError("审批人身份已撤销，禁止写入权威系统")
            return CurrentUser(user_id=identity.user_id, tenant_id=identity.tenant_id,
                               roles=list(identity.roles), depts=[identity.dept_id],
                               data_scope=identity.data_scope)
        # Deterministic denial must not create an UNKNOWN external command.
        policy = await policy_service.get_thresholds(db, "leave")
        await authorize_tool(current_approver(), "leave", "create_or_update_oa_approval", session=db,
                       required_roles={"approver"}, policy_tools=policy.get("allowed_tools"))
        record, is_new = await claim(db, envelope)
        await db.commit()  # durable claim before the external write
        record_id = record.id
        external_started = False
        async def write_external():
            nonlocal external_started
            external_started = True
            return await approval_tools.create_or_update_oa_approval(adapter, command)
        try:
            result = record.result if not is_new else await call_tool(db, scene="leave",
                tool_name="create_or_update_oa_approval", thread_id=_uuid(state), business_id=business_id,
                input_summary={"action": "approve", "actor_id": command.actor_id},
                actor=current_approver(),
                fn=write_external)
        except Exception:
            pending = await db.get(IdempotencyRecord, record_id)
            pending.status = "UNKNOWN" if external_started else "FAILED"
            if not external_started:
                pending.result = {"not_called": True}
            await db.commit()
            raise
        if not result or not result.get("success") or result.get("status") != "approve" or not result.get("request_id"):
            pending = await db.get(IdempotencyRecord, record_id)
            pending.status = "UNKNOWN"
            await db.commit()
            raise RuntimeError("权威审批写入未确认，审批保持待确认")
        if is_new:
            pending = await db.get(IdempotencyRecord, record_id)
            await complete(db, pending, result)
            pending.external_request_id = result["request_id"]
        await approval_service.finalize_approval(db, _uuid(state), result.get("request_id"))
        await audit_service.audit(
            db,
            AuditAction.BUSINESS_WRITE.value,
            thread_id=_uuid(state),
            business_id=business_id,
            target_type="approval",
            target_id=result.get("payload", {}).get("approval_id", business_id),
            input_summary={
                "action": command.action,
                "comment": command.comment[:512],
            },
            output_summary={
                "status": result.get("status"),
                "request_id": result.get("request_id"),
            },
        )
        await db.commit()
    return {"next_action": "approved"}


async def reject_summary(state: LeaveState) -> dict:
    """驳回摘要：生成结构化驳回说明与修改建议。

    Args:
        state: 请假子图状态。

    Returns:
        dict: 更新后的 next_action。
    """
    decision = state.get("human_decision") or {}
    comment = decision.get("comment", "")
    try:
        summary = await LLMFactory.get_llm().structured(
            [{"role": "user", "content": f"审批驳回理由：{comment}"}], RejectSummary)
        answer = {"reject_summary": summary.summary, "fix_hints": summary.fix_hints}
    except Exception as exc:
        logger.warning("驳回摘要模型不可用，使用确定性摘要: %s", exc)
        answer = {"reject_summary": f"审批未通过：{comment[:256]}",
                  "fix_hints": ["请查看驳回意见并修改请假材料后重新预检"]}
    return {
        "next_action": "rejected",
        "answer": answer,
    }


async def notify_outcome(state: LeaveState) -> dict:
    """通知节点：根据审批结果通知申请人。

    Args:
        state: 请假子图状态。

    Returns:
        dict: 空更新（通知为副作用）。
    """
    adapter = get_adapter()
    business_id = state["business_id"]
    next_action = state.get("next_action", "")
    if next_action == "approved":
        title = "请假审批通过"
        body = f"您的请假申请 {business_id} 已通过审批。"
    else:
        title = "请假审批被驳回"
        body = f"您的请假申请 {business_id} 被驳回，请查看详情并修改后重新提交。"
    from uuid import uuid4
    key = f"notify-{_uuid(state)}-{next_action}"
    envelope = CommandEnvelope(command_id=uuid4(), idempotency_key=key,
        actor_id="system", tenant_id=state["tenant_id"], resource_type="approval_outcome_notification",
        resource_id=business_id, trace_id=state.get("trace_id") or str(uuid4()),
        payload={"user_id": state["user_id"], "title": title, "body": body})
    async with async_session_factory() as db:
        record, is_new = await claim(db, envelope)
        await db.commit()  # never send before the command is durable
        if is_new:
            try:
                result = await notify_tools.notify_user(adapter, user_id=state["user_id"],
                    title=title, body=body, business_id=business_id, idempotency_key=key)
            except Exception:
                record.status = "UNKNOWN"  # response may be lost after delivery
                await audit_service.audit(db, AuditAction.ERROR_OCCURRED.value,
                    thread_id=_uuid(state), business_id=business_id, actor_id="system",
                    error_code=ErrorCode.DEPENDENCY_FAILED.value, input_summary={"step": "notify_outcome", "key": key})
                await db.commit()
                raise
            if not result.get("delivered") or not result.get("success") or not result.get("request_id"):
                record.status = "UNKNOWN"
                await db.commit()
                raise RuntimeError("通知结果未确认，须人工核对")
            await complete(db, record, result)
            record.external_request_id = result["request_id"]
            await audit_service.audit(db, AuditAction.NOTIFICATION_SENT.value,
                thread_id=_uuid(state), business_id=business_id, actor_id="system",
                input_summary={"type": "approval_outcome", "key": key})
            await db.commit()
    return {}


def _paused(code: str, msg: str) -> dict:
    """构造依赖失败/暂停状态片段。

    Args:
        code: 错误码。
        msg: 错误描述。

    Returns:
        dict: 状态片段。
    """
    return {"next_action": "paused", "error": {"code": code, "msg": msg}}


def _uuid(state: LeaveState):
    """从状态提取 thread_id 的 UUID（可能为字符串）。

    Args:
        state: 图状态。

    Returns:
        UUID: 会话 ID。
    """
    from uuid import UUID

    raw = state.get("thread_id")
    return UUID(str(raw)) if raw else None


async def merge_edited(state: LeaveState) -> dict:
    """合并编辑数据：审批人编辑后回写 OA 并重新进入预检。

    Args:
        state: 请假子图状态。

    Returns:
        dict: 更新后的状态片段（回 precheck）。
    """
    adapter = get_adapter()
    decision = state.get("human_decision") or {}
    edited = decision.get("edited_data") or {}
    if edited:
        from uuid import uuid4
        business_id = state["business_id"]
        prechecked = LeaveCase.model_validate(state["form_snapshot"])
        key = f"edit-{_uuid(state)}-{decision['idempotency_key'].removeprefix('interrupt:')}"
        envelope = CommandEnvelope(command_id=uuid4(), idempotency_key=key,
            actor_id=decision["actor_id"], tenant_id=state["tenant_id"],
            resource_type="leave_form_edit", resource_id=business_id,
            trace_id=state.get("trace_id") or str(uuid4()),
            payload={"expected_form": prechecked.model_dump(mode="json"), "fields": edited})
        command = LeaveEditCommand(business_id=business_id, idempotency_key=key,
            actor_id=decision["actor_id"], expected_form=prechecked, fields=edited)
        async with async_session_factory() as db:
            existing = (await db.scalars(select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == envelope.tenant_id,
                IdempotencyRecord.actor_id == envelope.actor_id,
                IdempotencyRecord.resource_type == envelope.resource_type,
                IdempotencyRecord.resource_id == envelope.resource_id,
                IdempotencyRecord.idempotency_key == envelope.idempotency_key))).one_or_none()
            if existing is not None and existing.status == 'SUCCEEDED':
                return {'next_action': 'route'}
            if existing is not None and existing.status in {'UNKNOWN', 'PENDING'}:
                raise RuntimeError('表单编辑结果尚未核对，禁止重复写入')
            record, is_new = await claim(db, envelope)
            if is_new:
                record.result = {"pending_payload": envelope.payload}
            await db.commit()
            if is_new:
                try:
                    approval_service.verify_authoritative_form(business_id, state["user_id"],
                        state.get("form_snapshot"))
                except Exception:
                    record.status = "FAILED"
                    record.result = {"not_called": True}
                    await db.commit()
                    raise
                try:
                    result = adapter.edit_leave_case(command).model_dump()
                except Exception:
                    record.status = "UNKNOWN"
                    await db.commit()
                    raise
                if not result.get("success") or result.get("status") != "edited" or not result.get("request_id"):
                    record.status = "UNKNOWN"
                    await db.commit()
                    raise RuntimeError("表单编辑未由 OA 确认，需按原请求核对")
                await complete(db, record, result)
                record.external_request_id = result["request_id"]
                await audit_service.audit(db, AuditAction.BUSINESS_WRITE.value,
                    thread_id=_uuid(state), business_id=business_id, actor_id=decision["actor_id"],
                    input_summary={"action": "edit", "fields": sorted(edited)})
                await db.commit()
    return {"next_action": "route"}


async def needs_fix(state: LeaveState) -> dict:
    """NEEDS_FIX 终态节点：标记状态供上层读取。

    Args:
        state: 请假子图状态。

    Returns:
        dict: 状态片段。
    """
    return {"next_action": "needs_fix"}


async def paused(state: LeaveState) -> dict:
    """PAUSED 终态节点：标记暂停状态供上层读取。

    Args:
        state: 请假子图状态。

    Returns:
        dict: 状态片段。
    """
    return {"next_action": state.get("next_action", "paused")}
