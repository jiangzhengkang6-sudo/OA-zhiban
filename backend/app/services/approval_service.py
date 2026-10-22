"""Authoritative ordered node decisions, independent of LangGraph checkpoints."""
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..models.approval_instance import ApprovalInstance
from ..models.approval_node import ApprovalNode
from ..models.approval_decision import ApprovalDecision
from ..models.human_decision import HumanDecision
from .idempotency_service import payload_digest


async def get_instance(db: AsyncSession, thread_id: UUID):
    return (await db.scalars(select(ApprovalInstance).where(ApprovalInstance.thread_id == thread_id)
                             .order_by(ApprovalInstance.version.desc()).limit(1))).one_or_none()


async def ensure_instance(db: AsyncSession, thread_id: UUID, tenant_id: str,
                          business_id: str, route: dict, version: int = 1) -> ApprovalInstance:
    """Create the first active node once, or reuse the identical version."""
    existing = await get_instance(db, thread_id)
    if existing and not (existing.status in {"REJECTED", "NEEDS_FIX"} and version > existing.version):
        if existing.tenant_id != tenant_id or existing.business_id != business_id or existing.version != version:
            raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "审批实例与申请版本不一致", http_status=409)
        return existing
    nodes = sorted(route.get("nodes", []), key=lambda item: item.get("order", 0))
    if not nodes or any(not item.get("approver_id") for item in nodes):
        raise AppException(ErrorCode.INVALID_STATE, "审批链缺少有效审批人", http_status=422)
    orders = [item["order"] for item in nodes]
    if len(orders) != len(set(orders)):
        raise AppException(ErrorCode.INVALID_STATE, "审批链节点顺序重复", http_status=422)
    instance = ApprovalInstance(thread_id=thread_id, tenant_id=tenant_id,
        business_id=business_id, version=version, route_version=route.get("rule_version", "v1"), status="ACTIVE")
    db.add(instance)
    await db.flush()
    now = datetime.now(timezone.utc)
    for position, item in enumerate(nodes):
        db.add(ApprovalNode(instance_id=instance.id, node_order=item["order"],
            approver_id=item["approver_id"], approver_name=item.get("approver_name") or item["approver_id"],
            is_proxy=item.get("is_proxy", False), status="ACTIVE" if position == 0 else "PENDING",
            waiting_since=now if position == 0 else None))
    await db.flush()
    return instance


async def active_node(db: AsyncSession, thread_id: UUID) -> ApprovalNode | None:
    instance = await get_instance(db, thread_id)
    if not instance or instance.status not in {"ACTIVE", "ESCALATED"}:
        return None
    return (await db.scalars(select(ApprovalNode).where(ApprovalNode.instance_id == instance.id,
        ApprovalNode.status == "ACTIVE"))).one_or_none()


def validate_edit(action: str, comment: str, edited_data: dict | None):
    if action == "edit":
        allowed = {"leave_type", "start_at", "end_at", "reason", "attachments"}
        if not edited_data or set(edited_data) - allowed or not comment.strip():
            raise AppException(ErrorCode.BAD_REQUEST, "编辑后批准需说明原因并提供允许编辑的表单字段", http_status=400)
    if action == "reject" and not comment.strip():
        raise AppException(ErrorCode.BAD_REQUEST, "驳回必须填写理由", http_status=400)
    if action == "reject" and (edited_data or {}).get("reason_category", "other") not in {
            "materials", "policy", "balance", "scheduling", "other"}:
        raise AppException(ErrorCode.BAD_REQUEST, "未知的驳回理由分类", http_status=400)
    if action == "reject" and set(edited_data or {}) - {"reason_category"}:
        raise AppException(ErrorCode.BAD_REQUEST, "驳回决定不允许修改请假表单", http_status=400)


async def record_decision(db: AsyncSession, thread_id: UUID, actor_id: str, action: str,
                          comment: str, edited_data: dict | None, idempotency_key: str) -> str:
    if action not in {"approve", "edit", "reject"}:
        raise AppException(ErrorCode.INVALID_STATE, "请假审批不支持该操作", http_status=422)
    validate_edit(action, comment, edited_data)
    if not idempotency_key:
        raise AppException(ErrorCode.BAD_REQUEST, "缺少决定幂等键", http_status=400)
    instance = (await db.scalars(select(ApprovalInstance).where(ApprovalInstance.thread_id == thread_id)
                .order_by(ApprovalInstance.version.desc()).limit(1).with_for_update())).one_or_none()
    if instance is None:
        raise AppException(ErrorCode.INVALID_STATE, "审批实例不存在", http_status=409)
    digest = payload_digest({"actor_id": actor_id, "action": action,
                              "comment": comment, "edited_data": edited_data or {}})
    previous = (await db.scalars(select(ApprovalDecision).where(ApprovalDecision.instance_id == instance.id,
                ApprovalDecision.idempotency_key == idempotency_key))).one_or_none()
    if previous:
        if previous.payload_hash != digest:
            raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "重复决定载荷不一致", http_status=409)
        return previous.result_status
    if instance.status != "ACTIVE":
        raise AppException(ErrorCode.INVALID_STATE, "当前审批实例不可处理", http_status=409)
    node = (await db.scalars(select(ApprovalNode).where(ApprovalNode.instance_id == instance.id,
                                  ApprovalNode.status == "ACTIVE").with_for_update())).one_or_none()
    if node is None or node.approver_id != actor_id:
        raise AppException(ErrorCode.FORBIDDEN, "当前用户不是本级审批人", http_status=403)
    edit_diff = None
    if action == "edit":
        from ..adapters.factory import get_adapter
        from ..adapters.oa_adapter import LeaveCase
        from pydantic import ValidationError
        from ..models.leave_application import LeaveApplication
        application = (await db.scalars(select(LeaveApplication).where(
            LeaveApplication.thread_id == thread_id))).one_or_none()
        case = (LeaveCase(business_id=application.business_id, user_id=application.user_id,
                          **application.latest_fields) if application else
                get_adapter().get_leave_case(instance.business_id))
        if case is None:
            raise AppException(ErrorCode.INVALID_STATE, "申请材料不可用，无法编辑", http_status=409)
        old = case.model_dump(mode="json")
        try:
            LeaveCase.model_validate({**old, **edited_data})
        except ValidationError as exc:
            raise AppException(ErrorCode.BAD_REQUEST, "编辑后的申请字段无效", http_status=400) from exc
        edit_diff = {key: {"old": old.get(key), "new": value} for key, value in edited_data.items()
                     if old.get(key) != value}
        if not edit_diff:
            raise AppException(ErrorCode.BAD_REQUEST, "请至少修改一项申请字段", http_status=400)
    if action == "reject":
        node.status = "REJECTED"
        instance.status = "REJECTED"
        next_status = "rejected"
    elif action == "edit":
        # Re-precheck the modified form; current node remains the owner.
        next_status = "waiting_human"
    else:
        next_node = (await db.scalars(select(ApprovalNode).where(ApprovalNode.instance_id == instance.id,
            ApprovalNode.status == "PENDING", ApprovalNode.node_order > node.node_order)
            .order_by(ApprovalNode.node_order).limit(1).with_for_update())).one_or_none()
        node.status = "APPROVED"
        if next_node:
            # PostgreSQL checks the partial unique index on each statement;
            # retire the old active row before activating the next one.
            await db.flush()
            next_node.status = "ACTIVE"
            next_node.waiting_since = datetime.now(timezone.utc)
            next_status = "waiting_human"
        else:
            instance.status = "PENDING_WRITE"
            next_status = "pending_write"
    db.add(ApprovalDecision(instance_id=instance.id, node_id=node.id, actor_id=actor_id,
        action=action, comment=comment, edited_data=edit_diff if action == "edit" else
            ({"reason_category": (edited_data or {}).get("reason_category", "other")}
             if action == "reject" else edited_data), payload_hash=digest,
        idempotency_key=idempotency_key, result_status=next_status))
    await db.flush()
    return next_status


async def finalize_approval(db: AsyncSession, thread_id: UUID, external_request_id: str):
    instance = await get_instance(db, thread_id)
    if instance and instance.status == "APPROVED" and instance.external_request_id == external_request_id:
        return  # checkpoint reconciliation may replay this already-confirmed write
    if not instance or instance.status != "PENDING_WRITE" or not external_request_id:
        raise AppException(ErrorCode.INVALID_STATE, "审批结果尚未由权威系统确认", http_status=409)
    instance.status = "APPROVED"
    instance.external_request_id = external_request_id
    await db.flush()


async def approval_progress(db: AsyncSession, thread_id: UUID) -> tuple[dict | None, list[dict]]:
    instance = await get_instance(db, thread_id)
    if not instance:
        return None, []
    nodes = (await db.scalars(select(ApprovalNode).where(ApprovalNode.instance_id == instance.id)
              .order_by(ApprovalNode.node_order))).all()
    current = (next((n for n in nodes if n.status == "ACTIVE"), None)
               if instance.status in {"ACTIVE", "ESCALATED"} else None)
    return ({"node_id": str(current.id), "order": current.node_order,
             "approver_id": current.approver_id, "approver_name": current.approver_name,
             "waiting_since": current.waiting_since.isoformat() if current.waiting_since else None}
            if current else None,
            [{"order": n.node_order, "approver_id": n.approver_id,
              "approver_name": n.approver_name, "status": n.status} for n in nodes])


async def approval_details(db: AsyncSession, thread_id: UUID) -> dict:
    instance = await get_instance(db, thread_id)
    if instance is None:
        return {}
    current, nodes = await approval_progress(db, thread_id)
    decisions = (await db.execute(select(ApprovalDecision, ApprovalInstance.version)
        .join(ApprovalInstance, ApprovalDecision.instance_id == ApprovalInstance.id)
        .where(ApprovalInstance.thread_id == thread_id)
        .order_by(ApprovalDecision.created_at, ApprovalDecision.id))).all()
    recovery_action = None
    if instance.status == "PENDING_WRITE":
        from ..models.idempotency_record import IdempotencyRecord
        record = (await db.scalars(select(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == instance.tenant_id,
            IdempotencyRecord.resource_type == "approval_write",
            IdempotencyRecord.resource_id == instance.business_id,
            IdempotencyRecord.idempotency_key == f"approval-{thread_id}"))).one_or_none()
        recovery_action = ("retry" if record is None or
                           (record.status == "FAILED" and record.result == {"not_called": True})
                           else "reconcile")
    return {"approval_status": instance.status, "active_approval_node": current,
            "approval_recovery_action": recovery_action,
            "approval_nodes": nodes,
            "approval_decisions": [{"node_id": str(d.node_id), "actor_id": d.actor_id,
                                    "application_version": version,
                                    "action": d.action, "comment": d.comment,
                                    "edited_data": d.edited_data, "created_at": d.created_at.isoformat()}
                                   for d, version in decisions]}


def verify_authoritative_form(business_id: str, user_id: str, snapshot: dict | None) -> None:
    """Reject a write when the prechecked OA form is missing or has changed."""
    from ..adapters.factory import get_adapter
    from ..adapters.oa_adapter import LeaveCase
    from pydantic import ValidationError

    if not snapshot:
        raise AppException(ErrorCode.INVALID_STATE, "缺少可信的预检表单快照，需人工核对", http_status=409)
    try:
        prechecked = LeaveCase.model_validate(snapshot)
    except ValidationError as exc:
        raise AppException(ErrorCode.INVALID_STATE, "预检表单快照不可验证，需人工核对", http_status=409) from exc
    current = get_adapter().get_leave_case(business_id)
    if (prechecked.business_id != business_id or prechecked.user_id != user_id or
            current is None or current.model_dump(mode="json") != prechecked.model_dump(mode="json")):
        raise AppException(ErrorCode.INVALID_STATE, "请假单已变更，需重新预检并人工核对", http_status=409)


async def adopt_legacy_pending(db: AsyncSession, thread, interrupt_payload: dict) -> ApprovalInstance:
    """Reconstruct only verified pending MVP requests; never invent an approval."""
    existing = await get_instance(db, thread.id)
    if existing:
        return existing
    from ..adapters.factory import get_adapter
    precheck = interrupt_payload.get("precheck") or {}
    route = interrupt_payload.get("approval_route") or {}
    case = get_adapter().get_leave_case(thread.business_id or "")
    if (not thread.current_interrupt_id or not precheck.get("passed") or case is None
            or case.user_id != thread.user_id or route.get("business_id") != thread.business_id):
        raise AppException(ErrorCode.INVALID_STATE, "旧请假任务缺少可验证的申请或审批链，需人工核对", http_status=409)
    verify_authoritative_form(thread.business_id, thread.user_id, interrupt_payload.get("form_snapshot"))
    instance = await ensure_instance(db, thread.id, thread.tenant_id, thread.business_id, route)
    prior = (await db.scalars(select(HumanDecision).where(
        HumanDecision.thread_id == thread.id, HumanDecision.action == "approve",
        HumanDecision.interrupt_id != thread.current_interrupt_id,
    ).order_by(HumanDecision.created_at, HumanDecision.id))).all()
    for old in prior:
        current = await active_node(db, thread.id)
        if current is None or current.approver_id != old.actor_id:
            raise AppException(ErrorCode.INVALID_STATE, "旧审批决定与审批链不一致，需人工核对", http_status=409)
        outcome = await record_decision(db, thread.id, old.actor_id, "approve", old.comment or "",
                                        None, f"legacy:{old.id}")
        if outcome == "pending_write":
            raise AppException(ErrorCode.INVALID_STATE, "旧审批已结束但权威结果未核对", http_status=409)
    return instance


async def reconcile_final_write(db: AsyncSession, thread, actor) -> str:
    """Complete an uncertain external write only after authoritative lookup."""
    from ..adapters.factory import get_adapter
    from ..models.idempotency_record import IdempotencyRecord
    from ..schemas.command import CommandEnvelope
    from .idempotency_service import resolve_unknown
    from ..repositories.thread_repo import update_thread_status
    instance = (await db.scalars(select(ApprovalInstance).where(
        ApprovalInstance.thread_id == thread.id).order_by(ApprovalInstance.version.desc())
        .limit(1).with_for_update())).one_or_none()
    if instance is None or instance.tenant_id != actor.tenant_id:
        raise AppException(ErrorCode.FORBIDDEN, "无权核对该审批", http_status=403)
    if instance.status == 'ACTIVE':
        return await _reconcile_form_edit(db, thread, instance, actor)
    final = (await db.scalars(select(ApprovalDecision).where(
        ApprovalDecision.instance_id == instance.id, ApprovalDecision.result_status == "pending_write")
        .order_by(ApprovalDecision.created_at.desc()).limit(1))).one_or_none()
    if final is None or not ("admin" in actor.roles or
                             (actor.user_id == final.actor_id and "approver" in actor.roles)):
        raise AppException(ErrorCode.FORBIDDEN, "仅最终审批人或管理员可核对", http_status=403)
    if instance.status == "APPROVED":
        await _reconcile_outcome_notification(db, thread)
        return "APPROVED"
    if instance.status != "PENDING_WRITE" or thread.status != "PAUSED":
        raise AppException(ErrorCode.INVALID_STATE, "当前审批不处于待核对状态", http_status=409)
    key = f"approval-{thread.id}"
    record = (await db.scalars(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == thread.tenant_id, IdempotencyRecord.actor_id == final.actor_id,
        IdempotencyRecord.resource_type == "approval_write", IdempotencyRecord.resource_id == thread.business_id,
        IdempotencyRecord.idempotency_key == key).with_for_update())).one_or_none()
    if record is None:
        raise AppException(ErrorCode.INVALID_STATE, "审批写入凭据不存在，须人工核对", http_status=409)
    adapter = get_adapter()
    lookup = getattr(adapter, "get_approval_result", None)
    if lookup is None:
        raise AppException(ErrorCode.DEPENDENCY_FAILED, "当前 OA 不支持按原幂等键核对，请人工接管", http_status=502)
    outcome = lookup(key)
    if outcome is None or not outcome.success or outcome.status != "approve" or not outcome.request_id:
        raise AppException(ErrorCode.DEPENDENCY_FAILED, "OA 尚未确认审批结果，保持暂停等待人工处理", http_status=502)
    if record.status != "SUCCEEDED":
        envelope = CommandEnvelope(command_id=record.command_id, idempotency_key=key,
            actor_id=record.actor_id, tenant_id=record.tenant_id, resource_type="approval_write",
            resource_id=record.resource_id, trace_id=record.trace_id,
            payload={"business_id": thread.business_id, "action": "approve",
                     "version": instance.version, "actor_id": final.actor_id})
        await resolve_unknown(db, envelope, outcome.model_dump(), outcome.request_id)
    await finalize_approval(db, thread.id, outcome.request_id)
    await update_thread_status(db, thread, "APPROVED", current_interrupt_id=None,
                               error_code=None, error_msg=None)
    return "APPROVED"


async def _reconcile_form_edit(db: AsyncSession, thread, instance, actor) -> str:
    from ..adapters.factory import get_adapter
    from ..adapters.oa_adapter import LeaveCase
    from ..models.idempotency_record import IdempotencyRecord
    from ..schemas.command import CommandEnvelope
    from .idempotency_service import resolve_unknown

    node = await active_node(db, thread.id)
    decision = (await db.scalars(select(ApprovalDecision).where(
        ApprovalDecision.instance_id == instance.id).order_by(
            ApprovalDecision.created_at.desc(), ApprovalDecision.id.desc()).limit(1))).one_or_none()
    if (node is None or decision is None or decision.action != 'edit' or
            decision.node_id != node.id or not ('admin' in actor.roles or
                (actor.user_id == node.approver_id == decision.actor_id and 'approver' in actor.roles))):
        raise AppException(ErrorCode.FORBIDDEN, '仅当前编辑审批人或管理员可核对', http_status=403)
    if thread.status != 'PAUSED':
        raise AppException(ErrorCode.INVALID_STATE, '表单编辑不处于暂停核对状态', http_status=409)
    key = f"edit-{thread.id}-{decision.idempotency_key.removeprefix('interrupt:')}"
    record = (await db.scalars(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == thread.tenant_id, IdempotencyRecord.actor_id == decision.actor_id,
        IdempotencyRecord.resource_type == 'leave_form_edit',
        IdempotencyRecord.resource_id == thread.business_id,
        IdempotencyRecord.idempotency_key == key).with_for_update())).one_or_none()
    if record is None or record.status not in {'UNKNOWN', 'PENDING', 'SUCCEEDED'}:
        raise AppException(ErrorCode.INVALID_STATE, '缺少可核对的表单编辑凭据', http_status=409)
    adapter = get_adapter()
    lookup = getattr(adapter, 'get_leave_edit_result', None)
    outcome = lookup(key) if lookup else None
    if (outcome is None or not outcome.success or outcome.status != 'edited' or
            not outcome.request_id or outcome.idempotency_key != key or
            outcome.payload.get('business_id') != thread.business_id):
        raise AppException(ErrorCode.DEPENDENCY_FAILED, 'OA 尚未确认原表单编辑请求，保持暂停', http_status=502)
    if record.status != 'SUCCEEDED':
        payload = (record.result or {}).get('pending_payload')
        if not payload or payload_digest(payload) != record.payload_hash:
            raise AppException(ErrorCode.INVALID_STATE, '原编辑载荷无法验证，须人工核对', http_status=409)
        expected = LeaveCase.model_validate({**payload['expected_form'], **payload['fields']})
        current = adapter.get_leave_case(thread.business_id)
        if (expected.business_id != thread.business_id or expected.user_id != thread.user_id or
                current is None or current.model_dump(mode='json') != expected.model_dump(mode='json')):
            raise AppException(ErrorCode.DEPENDENCY_FAILED, '权威表单与原编辑结果不一致，保持暂停', http_status=502)
        envelope = CommandEnvelope(command_id=record.command_id, idempotency_key=key,
            actor_id=record.actor_id, tenant_id=record.tenant_id, resource_type=record.resource_type,
            resource_id=record.resource_id, trace_id=record.trace_id, payload=payload)
        await resolve_unknown(db, envelope, outcome.model_dump(), outcome.request_id)
    return 'WAITING_HUMAN'


async def _reconcile_outcome_notification(db: AsyncSession, thread) -> None:
    from ..adapters.factory import get_adapter
    from ..models.idempotency_record import IdempotencyRecord
    from ..schemas.command import CommandEnvelope
    from .idempotency_service import resolve_unknown

    key = f'notify-{thread.id}-approved'
    record = (await db.scalars(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == thread.tenant_id, IdempotencyRecord.actor_id == 'system',
        IdempotencyRecord.resource_type == 'approval_outcome_notification',
        IdempotencyRecord.resource_id == thread.business_id,
        IdempotencyRecord.idempotency_key == key).with_for_update())).one_or_none()
    if record is None or record.status == 'SUCCEEDED':
        return
    lookup = getattr(get_adapter(), 'get_notification_result', None)
    outcome = lookup(key) if lookup else None
    if (outcome is None or not outcome.success or not outcome.delivered or
            not outcome.request_id or outcome.idempotency_key != key):
        raise AppException(ErrorCode.DEPENDENCY_FAILED, '通知结果尚未确认，保持暂停且禁止重复发送', http_status=502)
    envelope = CommandEnvelope(command_id=record.command_id, idempotency_key=key,
        actor_id=record.actor_id, tenant_id=record.tenant_id, resource_type=record.resource_type,
        resource_id=record.resource_id, trace_id=record.trace_id,
        payload={'user_id': thread.user_id, 'title': '请假审批通过',
                 'body': f'您的请假申请 {thread.business_id} 已通过审批。'})
    await resolve_unknown(db, envelope, outcome.model_dump(), outcome.request_id)


async def validate_safe_retry(db: AsyncSession, thread, actor) -> None:
    from ..models.idempotency_record import IdempotencyRecord
    instance = await get_instance(db, thread.id)
    if instance is None or instance.tenant_id != actor.tenant_id:
        raise AppException(ErrorCode.FORBIDDEN, "无权重试该审批", http_status=403)
    if instance.status != "PENDING_WRITE" or thread.status != "PAUSED":
        raise AppException(ErrorCode.INVALID_STATE, "审批任务不处于可重试的暂停状态", http_status=409)
    last = (await db.scalars(select(ApprovalDecision).where(
        ApprovalDecision.instance_id == instance.id, ApprovalDecision.result_status == "pending_write")
        .order_by(ApprovalDecision.created_at.desc()).limit(1))).one_or_none()
    if last is None or not ("admin" in actor.roles or
                            (last.actor_id == actor.user_id and "approver" in actor.roles)):
        raise AppException(ErrorCode.FORBIDDEN, "仅最终审批人或管理员可安全重试", http_status=403)
    record = (await db.scalars(select(IdempotencyRecord).where(
        IdempotencyRecord.tenant_id == thread.tenant_id,
        IdempotencyRecord.resource_type == "approval_write",
        IdempotencyRecord.resource_id == thread.business_id,
        IdempotencyRecord.idempotency_key == f"approval-{thread.id}"))).one_or_none()
    if record and not (record.status == "FAILED" and record.result == {"not_called": True}):
        raise AppException(ErrorCode.INVALID_STATE, "外部审批写入结果不确定，只能核对原请求，禁止重发", http_status=409)
