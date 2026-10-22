"""Versioned task commands with live source checks and atomic local effects."""
import asyncio
import json
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from ..adapters.factory import get_adapter
from ..core.context import CurrentUser, get_trace_id
from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..models.agent_thread import AgentThread
from ..models.approval_instance import ApprovalInstance
from ..models.approval_node import ApprovalNode
from ..models.leave_application import LeaveApplication
from ..models.meeting_record import MeetingRecord
from ..models.meeting_draft_version import MeetingDraftVersion
from ..models.meeting_decision import MeetingDecision
from ..models.ticket_record import TicketRecord
from ..models.work_task import WorkTask
from ..models.work_task_batch import WorkTaskBatch
from ..models.work_task_draft_version import WorkTaskDraftVersion
from ..models.work_task_event import WorkTaskEvent
from ..models.work_task_notification import WorkTaskNotification
from ..schemas.command import CommandEnvelope
from ..schemas.work_task import WorkTaskBatchResponse, WorkTaskResponse, WorkTaskPage
from . import audit_service, idempotency_service, policy_service, degradation_service, work_task_generator, runtime_trace_service
from .authorization_service import require_business_identity, require_permission, resource_clause, business_boundary


async def _identity(session, actor):
    fresh = await require_business_identity(actor, session=session)
    require_permission(fresh, 'work_task', 'read')
    return fresh


def _deny(message="无权访问该任务来源", status=403):
    raise AppException(ErrorCode.FORBIDDEN if status == 403 else ErrorCode.INVALID_STATE, message, http_status=status)


async def _available(session, actor, record=None):
    if not await policy_service.is_scene_enabled(session, "work_task", actor.user_id,
            actor.depts[0] if actor.depts else "", actor.tenant_id):
        raise AppException(ErrorCode.DEGRADED, "工作任务智能路径已关闭", http_status=503)
    state = await degradation_service.resolve(session, scene="work_task", user=actor)
    if state and (state.new_task_action if record is None or record.created_at >= state.created_at else state.inflight_action) != "continue":
        raise AppException(ErrorCode.DEGRADED, "工作任务场景处于降级状态", http_status=503)


@business_boundary('work_task', 'read')
async def load_source(session, actor, source_type, source_id, source_version=None):
    """Only authoritative local sources; source text cannot expand authority."""
    actor = await _identity(session, actor)
    if actor.data_scope.get('identity_provider') == 'builtin':
        from . import oa_derived_source
        if source_type == 'ticket':
            return await oa_derived_source.ticket_source(session, actor, source_id, source_version)
        if source_type == 'approval':
            return await oa_derived_source.approval_source(session, actor, source_id, source_version)
        if source_type == 'meeting':
            require_permission(actor, 'meeting', 'read')
    if source_type == "meeting":
        record = await session.scalar(select(MeetingRecord).where(MeetingRecord.meeting_id == source_id,
            MeetingRecord.tenant_id == actor.tenant_id, MeetingRecord.owner_id == actor.user_id))
        if not record:
            _deny()
        version_number = int(source_version) if source_version is not None else record.current_version
        draft = await session.scalar(select(MeetingDraftVersion).where(
            MeetingDraftVersion.meeting_id == record.id, MeetingDraftVersion.version == version_number))
        if not draft or not await session.scalar(select(MeetingDecision.id).where(
                MeetingDecision.meeting_id == record.id, MeetingDecision.draft_version_id == draft.id,
                MeetingDecision.action == "confirm")):
            _deny("会议版本尚未确认", 422)
        content = json.dumps({"summary": draft.summary, "action_items": draft.action_items}, ensure_ascii=False)
        version = str(draft.version)
        actions = draft.action_items
        title = record.title
    elif source_type == "ticket":
        record = await session.scalar(select(TicketRecord).where(TicketRecord.ticket_id == source_id,
            TicketRecord.tenant_id == actor.tenant_id,
            or_(TicketRecord.user_id == actor.user_id, TicketRecord.assignee_id == actor.user_id)))
        if not record:
            _deny()
        content = record.summary
        version = sha256(json.dumps({"summary": record.summary, "status": record.status,
            "context": record.context}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        actions, title = [], record.ticket_id
    elif source_type == "approval":
        query = select(ApprovalInstance).where(ApprovalInstance.tenant_id == actor.tenant_id,
            ApprovalInstance.business_id == source_id)
        if source_version is not None:
            query = query.where(ApprovalInstance.version == int(source_version))
        record = await session.scalar(query.order_by(ApprovalInstance.version.desc()).limit(1))
        if not record or record.status not in {"APPROVED", "REJECTED", "CANCELLED"}:
            _deny("审批结果尚未结束或无权读取", 422)
        application = await session.scalar(select(LeaveApplication).where(
            LeaveApplication.thread_id == record.thread_id, LeaveApplication.tenant_id == actor.tenant_id))
        participated = "approver" in actor.roles and await session.scalar(select(ApprovalNode.id).where(
            ApprovalNode.instance_id == record.id, ApprovalNode.approver_id == actor.user_id))
        if not (application and application.user_id == actor.user_id) and not participated:
            _deny()
        content = f"{record.business_id}: {record.status}; version {record.version}"
        actions, title, version = [], record.business_id, str(record.version)
    else:
        _deny("不支持的来源", 422)
    if len(content) > 30000:
        _deny("来源超过 30000 字符限制", 422)
    return dict(ref=f"{source_type}:{source_id}:{version}", source_type=source_type,
        source_id=source_id, version=version, title=title, content=content,
        content_hash=sha256(content.encode()).hexdigest(), action_items=actions)


async def _source_access(session, actor, batch):
    version = int(batch.source_version) if batch.source_type in {"meeting", "approval"} else None
    await load_source(session, actor, batch.source_type, batch.source_id, version)


async def _batch(session, actor, batch_id, lock=False):
    actor = await _identity(session, actor)
    query = select(WorkTaskBatch).where(WorkTaskBatch.batch_id == batch_id,
        WorkTaskBatch.tenant_id == actor.tenant_id, WorkTaskBatch.owner_id == actor.user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    batch = await session.scalar(query)
    if not batch:
        raise AppException(ErrorCode.NOT_FOUND, "候选批次不存在", http_status=404)
    await _source_access(session, actor, batch)
    return batch


async def _claim(session, actor, resource_id, action, payload):
    data = payload.model_dump(mode="json", exclude={"idempotency_key"})
    return await idempotency_service.claim(session, CommandEnvelope(command_id=uuid4(),
        idempotency_key=payload.idempotency_key, actor_id=actor.user_id, tenant_id=actor.tenant_id,
        resource_type="work_task", resource_id=resource_id, trace_id=get_trace_id() or uuid4().hex,
        payload={"operation": action, **data}))


def _expect(actual, expected):
    if actual != expected:
        raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "版本已变化，请刷新后操作", http_status=409)


async def _batch_response(session, batch):
    draft = await session.scalar(select(WorkTaskDraftVersion).where(
        WorkTaskDraftVersion.batch_id == batch.id, WorkTaskDraftVersion.version == batch.current_version))
    task_ids = list((await session.scalars(select(WorkTask.task_id).where(WorkTask.batch_id == batch.id))).all())
    actions = {"CREATED": ["extract"], "DRAFT_READY": ["edit", "confirm", "reject"], "PAUSED": ["retry"]}.get(batch.status, [])
    return WorkTaskBatchResponse(batch_id=batch.batch_id, thread_id=str(batch.thread_id), source_type=batch.source_type,
        source_id=batch.source_id, source_version=batch.source_version, source=batch.source_snapshot,
        status=batch.status, version=batch.current_version, draft={"candidates": draft.candidates} if draft else None,
        available_actions=actions, task_ids=task_ids, error=batch.error, created_at=batch.created_at, updated_at=batch.updated_at)


async def _batch_finish(session, actor, batch, command, operation):
    thread = await session.get(AgentThread, batch.thread_id)
    thread.status = {"CREATED": "DRAFT", "DRAFT_READY": "WAITING_HUMAN", "PAUSED": "PAUSED",
        "CONFIRMED": "COMPLETED", "REJECTED": "REJECTED"}[batch.status]
    thread.waiting_since = None
    thread.error_code = batch.error["code"] if batch.error else None
    thread.error_msg = batch.error["message"] if batch.error else None
    await audit_service.audit(session, "work_task_" + operation, thread_id=batch.thread_id,
        business_id=batch.batch_id, actor_id=actor.user_id, target_type="work_task_batch", target_id=batch.batch_id,
        output_summary={"status": batch.status, "version": batch.current_version, "external_writes": False})
    await session.flush()
    await session.refresh(batch)
    response = await _batch_response(session, batch)
    await idempotency_service.complete(session, command, response.model_dump(mode="json"))
    return response


@business_boundary('work_task', 'write')
async def create_batch(session, actor, payload):
    actor = await _identity(session, actor)
    source = await load_source(session, actor, payload.source_type, payload.source_id, payload.source_version)
    command, fresh = await _claim(session, actor, "create_batch", "create_batch", payload)
    if not fresh:
        await _batch(session, actor, command.result["batch_id"])
        return WorkTaskBatchResponse.model_validate(command.result)
    await _available(session, actor)
    batch_id = "WTB-" + uuid4().hex[:12].upper()
    thread = AgentThread(tenant_id=actor.tenant_id, user_id=actor.user_id, scene="work_task",
        intent="work_task", status="DRAFT", business_id=batch_id)
    session.add(thread)
    await session.flush()
    batch = WorkTaskBatch(batch_id=batch_id, thread_id=thread.id, tenant_id=actor.tenant_id,
        owner_id=actor.user_id, source_type=payload.source_type, source_id=payload.source_id,
        source_version=source["version"], source_snapshot=source, idempotency_key=payload.idempotency_key)
    session.add(batch)
    await session.flush()
    return await _batch_finish(session, actor, batch, command, "created")


@business_boundary('work_task', 'read')
async def get_batch(session, actor, batch_id):
    return await _batch_response(session, await _batch(session, actor, batch_id))


@business_boundary('work_task', 'read')
async def list_batches(session, actor):
    actor = await _identity(session, actor)
    batches = (await session.scalars(select(WorkTaskBatch).where(WorkTaskBatch.tenant_id == actor.tenant_id,
        WorkTaskBatch.owner_id == actor.user_id).order_by(WorkTaskBatch.updated_at.desc()).limit(100))).all()
    result = []
    for batch in batches:
        try:
            await _source_access(session, actor, batch)
        except AppException as exc:
            if exc.http_status not in {403, 404, 422}:
                raise
            continue
        result.append(await _batch_response(session, batch))
    return result


@business_boundary('work_task', 'read')
async def versions(session, actor, batch_id):
    batch = await _batch(session, actor, batch_id)
    rows = (await session.scalars(select(WorkTaskDraftVersion).where(WorkTaskDraftVersion.batch_id == batch.id)
        .order_by(WorkTaskDraftVersion.version))).all()
    return [dict(version=r.version, draft={"candidates": r.candidates}, edited_by=r.edited_by, created_at=r.created_at) for r in rows]


async def _save(session, actor, batch, candidates, edited=False):
    try:
        candidates = work_task_generator.validate_candidates(candidates, batch.source_snapshot["ref"])
    except ValueError:
        _deny("候选引用或格式无效", 422)
    if batch.current_version:
        previous = await session.scalar(select(WorkTaskDraftVersion).where(
            WorkTaskDraftVersion.batch_id == batch.id, WorkTaskDraftVersion.version == batch.current_version))
        if {c["candidate_id"] for c in candidates} != {c["candidate_id"] for c in previous.candidates}:
            _deny("不可修改来源候选标识", 422)
    batch.current_version += 1
    session.add(WorkTaskDraftVersion(batch_id=batch.id, version=batch.current_version,
        candidates=candidates, edited_by=actor.user_id if edited else None))
    batch.status, batch.error = "DRAFT_READY", None
    await session.flush()


@business_boundary('work_task', 'write')
async def extract(session, actor, batch_id, payload):
    actor = await _identity(session, actor)
    batch = await _batch(session, actor, batch_id, lock=True)
    command, fresh = await _claim(session, actor, batch_id, "extract", payload)
    if not fresh:
        return WorkTaskBatchResponse.model_validate(command.result)
    _expect(batch.current_version, payload.expected_version)
    if batch.status not in {"CREATED", "PAUSED"}:
        _deny("当前批次不可提取", 422)
    await _available(session, actor, batch)
    started = datetime.now(timezone.utc)
    result = {}
    try:
        from ..graph.work_task_graph import build_work_task_graph
        result = await asyncio.wait_for(build_work_task_graph().ainvoke({"source": batch.source_snapshot}), 25)
        if result.get("failed"):
            raise RuntimeError("task extraction failed")
    except Exception:
        actor = await _identity(session, actor)
        await _source_access(session, actor, batch)
        batch.status = "PAUSED"
        batch.error = dict(code=ErrorCode.DEPENDENCY_FAILED.value, trace_id=get_trace_id(), message="任务提取暂不可用，请重试")
    else:
        actor = await _identity(session, actor)
        await _source_access(session, actor, batch)
        await _save(session, actor, batch, result["candidates"])
    await runtime_trace_service.record_span(session, tenant_id=actor.tenant_id, trace_id=get_trace_id(),
        node_name="work_task.extract_candidates", tool_name=None, thread_id=batch.thread_id,
        started_at=started, finished_at=datetime.now(timezone.utc), status="failed" if batch.error else "completed")
    from ..core.config import get_settings
    usage = result.get("model_usage", {})
    settings = get_settings()
    await runtime_trace_service.record_model_attempts(session, tenant_id=actor.tenant_id, trace_id=get_trace_id(),
        usage=usage, provider=settings.llm_provider, model_name="work_task_extraction"
        if settings.llm_provider == "mock" else getattr(settings, f"{settings.llm_provider}_chat_model"))
    return await _batch_finish(session, actor, batch, command, "extracted")


@business_boundary('work_task', 'write')
async def save_draft(session, actor, batch_id, payload):
    actor = await _identity(session, actor)
    batch = await _batch(session, actor, batch_id, lock=True)
    command, fresh = await _claim(session, actor, batch_id, "save", payload)
    if not fresh:
        return WorkTaskBatchResponse.model_validate(command.result)
    _expect(batch.current_version, payload.expected_version)
    if batch.status != "DRAFT_READY":
        _deny("当前批次不可修改", 422)
    await _available(session, actor, batch)
    await _save(session, actor, batch, payload.draft.model_dump(mode="json")["candidates"], edited=True)
    return await _batch_finish(session, actor, batch, command, "saved")


async def _assignee(session, actor, user_id, priority, sensitive, acknowledged):
    try:
        from ..providers.identity import IdentityResolver
        target = await IdentityResolver().resolve(user_id, session=session)
    except AppException as exc:
        if exc.http_status in {401,403}:
            _deny('负责人不存在或已停用',422)
        raise
    except Exception:
        raise AppException(ErrorCode.DEPENDENCY_FAILED, "负责人身份暂不可用", http_status=502) from None
    if target is None or target.tenant_id != actor.tenant_id:
        _deny("负责人不存在或不属于当前租户", 422)
    if target.data_scope.get('identity_provider') == 'builtin':
        require_permission(target, 'work_task', 'read')
    elif not set(target.roles).intersection({'employee', 'approver', 'admin', 'ops'}):
        _deny('负责人没有业务访问权限', 422)
    risky = sensitive or priority == "high" or not set(target.depts).intersection(actor.depts)
    if risky and not acknowledged:
        _deny("跨部门、敏感或高优先级任务需要二次确认", 422)
    return target


@business_boundary('work_task', 'write')
async def decide(session, actor, batch_id, payload):
    actor = await _identity(session, actor)
    batch = await _batch(session, actor, batch_id, lock=True)
    command, fresh = await _claim(session, actor, batch_id, "decide", payload)
    if not fresh:
        return WorkTaskBatchResponse.model_validate(command.result)
    _expect(batch.current_version, payload.expected_version)
    if batch.status != "DRAFT_READY":
        _deny("当前批次不可决定", 422)
    await _available(session, actor, batch)
    if payload.action == "reject":
        if not payload.reason:
            _deny("拒绝必须填写原因", 422)
        batch.status = "REJECTED"
    else:
        if not payload.metadata_confirmed or not payload.selected_candidate_ids:
            _deny("需选择候选并显式核对负责人和截止时间", 422)
        version = await session.scalar(select(WorkTaskDraftVersion).where(
            WorkTaskDraftVersion.batch_id == batch.id, WorkTaskDraftVersion.version == batch.current_version))
        candidates = {c["candidate_id"]: c for c in version.candidates}
        if len(set(payload.selected_candidate_ids)) != len(payload.selected_candidate_ids) or not set(payload.selected_candidate_ids).issubset(candidates):
            _deny("候选选择无效", 422)
        for key in payload.selected_candidate_ids:
            candidate = candidates[key]
            if not candidate["assignee_id"] or not candidate["due_at"]:
                _deny("负责人和带时区截止时间不能为空", 422)
            await _assignee(session, actor, candidate["assignee_id"], candidate["priority"], candidate["sensitive"], payload.risk_acknowledged)
            candidate_values = {k: v for k, v in candidate.items() if k != "due_at"}
            values = dict(id=uuid4(), task_id="WT-" + uuid4().hex[:12].upper(), batch_id=batch.id,
                tenant_id=actor.tenant_id, creator_id=actor.user_id, source_type=batch.source_type,
                source_id=batch.source_id, source_version=batch.source_version, **candidate_values,
                due_at=datetime.fromisoformat(candidate["due_at"]), status="OPEN", progress=0, version=1, deadline_version=1)
            # Unique source candidate identity survives new command keys and batches.
            statement = insert(WorkTask).values(**values).on_conflict_do_nothing(constraint="uq_work_task_candidate").returning(WorkTask.id)
            task_uuid = await session.scalar(statement)
            if task_uuid is None:
                raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "来源候选已经创建过业务任务", http_status=409)
            session.add(WorkTaskEvent(task_id=task_uuid, actor_id=actor.user_id, action="created", version=1,
                details={"draft_version": batch.current_version, "risk_acknowledged": payload.risk_acknowledged}))
        batch.status = "CONFIRMED"
    return await _batch_finish(session, actor, batch, command, payload.action)


async def _task(session, actor, task_id, lock=False):
    actor = await _identity(session, actor)
    query = select(WorkTask).where(WorkTask.task_id == task_id, WorkTask.tenant_id == actor.tenant_id,
        or_(WorkTask.creator_id == actor.user_id, WorkTask.assignee_id == actor.user_id))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    task = await session.scalar(query)
    if not task:
        raise AppException(ErrorCode.NOT_FOUND, "工作任务不存在", http_status=404)
    return task


def _task_actions(task, actor):
    actions = []
    if task.status in {"OPEN", "IN_PROGRESS"}:
        if actor.user_id == task.creator_id:
            actions += ["edit", "cancel"]
        if actor.user_id == task.assignee_id:
            actions += ["start"] if task.status == "OPEN" else ["progress", "complete"]
    if task.status in {"COMPLETED", "CANCELLED"} and actor.user_id == task.creator_id:
        actions += ["archive"]
    return actions


async def _task_response(session, actor, task, include_source=True):
    batch = await session.get(WorkTaskBatch, task.batch_id)
    source = None
    if include_source:
        try:
            await _source_access(session, actor, batch)
            source = batch.source_snapshot
        except AppException as exc:
            if exc.http_status not in {403, 404, 422}:
                raise
    return WorkTaskResponse(task_id=task.task_id, batch_id=batch.batch_id, title=task.title, creator_id=task.creator_id,
        assignee_id=task.assignee_id, due_at=task.due_at, priority=task.priority, sensitive=task.sensitive,
        status=task.status, progress=task.progress, version=task.version, deadline_version=task.deadline_version,
        source_refs=task.source_refs if source else [], source=source, available_actions=_task_actions(task, actor),
        created_at=task.created_at, updated_at=task.updated_at)


@business_boundary('work_task', 'read')
async def get_task(session, actor, task_id):
    actor = await _identity(session, actor)
    return await _task_response(session, actor, await _task(session, actor, task_id))


@business_boundary('work_task', 'read')
async def list_tasks(session, actor, page=1, page_size=20):
    actor = await _identity(session, actor)
    page, page_size = max(1, page), min(100, max(1, page_size))
    query = select(WorkTask).where(WorkTask.tenant_id == actor.tenant_id,
        or_(WorkTask.creator_id == actor.user_id, WorkTask.assignee_id == actor.user_id))
    from sqlalchemy import func
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await session.scalars(query.order_by(WorkTask.updated_at.desc(), WorkTask.id)
        .offset((page - 1) * page_size).limit(page_size))).all()
    return WorkTaskPage(items=[await _task_response(session, actor, row, include_source=False) for row in rows],
        total=total, page=page, page_size=page_size)


async def _task_authority(session, actor, task):
    batch = await session.get(WorkTaskBatch, task.batch_id)
    creator = CurrentUser(user_id=task.creator_id, tenant_id=task.tenant_id)
    await _source_access(session, await _identity(session, creator), batch)
    await _available(session, actor, batch)


async def _task_replay(session, actor, task, command):
    current = await _task_response(session, actor, task)
    replay = WorkTaskResponse.model_validate(command.result)
    # Stored command results may contain formerly accessible source material.
    replay.source, replay.source_refs = current.source, current.source_refs
    replay.available_actions = current.available_actions
    return replay


async def _task_finish(session, actor, task, command, action, details):
    session.add(WorkTaskEvent(task_id=task.id, actor_id=actor.user_id, action=action, version=task.version, details=details))
    await audit_service.audit(session, "work_task_" + action, business_id=task.task_id,
        actor_id=actor.user_id, target_type="work_task", target_id=task.task_id,
        output_summary={"version": task.version, "status": task.status, "external_writes": False})
    await session.flush()
    await session.refresh(task)
    response = await _task_response(session, actor, task)
    await idempotency_service.complete(session, command, response.model_dump(mode="json"))
    return response


@business_boundary('work_task', 'write')
async def update_task(session, actor, task_id, payload):
    actor = await _identity(session, actor)
    task = await _task(session, actor, task_id, lock=True)
    await _task_authority(session, actor, task)
    if actor.user_id != task.creator_id:
        _deny("只有创建人可维护任务")
    command, fresh = await _claim(session, actor, task_id, "update", payload)
    if not fresh:
        return await _task_replay(session, actor, task, command)
    _expect(task.version, payload.expected_version)
    if task.status not in {"OPEN", "IN_PROGRESS"} or not payload.metadata_confirmed:
        _deny("仅未结束任务可在显式确认后修改", 422)
    await _assignee(session, actor, payload.assignee_id, payload.priority, payload.sensitive, payload.risk_acknowledged)
    if task.due_at != payload.due_at or task.assignee_id != payload.assignee_id:
        task.deadline_version += 1
        task.notification_scan_at = None
    for field in ("title", "assignee_id", "due_at", "priority", "sensitive"):
        setattr(task, field, getattr(payload, field))
    task.version += 1
    return await _task_finish(session, actor, task, command, "updated", {"risk_acknowledged": payload.risk_acknowledged})


@business_boundary('work_task', 'write')
async def task_command(session, actor, task_id, payload):
    actor = await _identity(session, actor)
    task = await _task(session, actor, task_id, lock=True)
    await _task_authority(session, actor, task)
    command, fresh = await _claim(session, actor, task_id, "command", payload)
    if not fresh:
        return await _task_replay(session, actor, task, command)
    _expect(task.version, payload.expected_version)
    if payload.action not in _task_actions(task, actor):
        _deny("当前身份或任务状态不可执行此动作", 422 if task.status in {"COMPLETED", "CANCELLED", "ARCHIVED"} else 403)
    if payload.action == "progress":
        if payload.progress is None or payload.progress < task.progress:
            _deny("进度不得为空或倒退", 422)
        task.progress = payload.progress
    else:
        task.status = {"start": "IN_PROGRESS", "complete": "COMPLETED", "cancel": "CANCELLED", "archive": "ARCHIVED"}[payload.action]
        if payload.action == "complete":
            task.progress = 100
    task.version += 1
    return await _task_finish(session, actor, task, command, payload.action,
        {"progress": task.progress, "comment": payload.comment})


@business_boundary('work_task', 'read')
async def events(session, actor, task_id):
    task = await _task(session, actor, task_id)
    rows = (await session.scalars(select(WorkTaskEvent).where(WorkTaskEvent.task_id == task.id)
        .order_by(WorkTaskEvent.version))).all()
    return [dict(action=e.action, version=e.version, actor_id=e.actor_id, details=e.details, created_at=e.created_at) for e in rows]


@business_boundary('work_task', 'read')
async def notifications(session, actor):
    actor = await _identity(session, actor)
    rows = (await session.execute(select(WorkTaskNotification, WorkTask).join(WorkTask)
        .where(WorkTaskNotification.tenant_id == actor.tenant_id, WorkTaskNotification.recipient_id == actor.user_id,
            or_(WorkTask.creator_id == actor.user_id, WorkTask.assignee_id == actor.user_id))
        .order_by(WorkTaskNotification.created_at.desc()).limit(100))).all()
    result = []
    for notice, task in rows:
        if notice.deadline_version != task.deadline_version:
            continue
        batch = await session.get(WorkTaskBatch, task.batch_id)
        try:
            await _source_access(session, actor, batch)
        except AppException as exc:
            if exc.http_status not in {403, 404, 422}:
                raise
            continue
        result.append(dict(id=str(notice.id), task_id=task.task_id, title=task.title, stage=notice.stage,
            due_at=task.due_at, read_at=notice.read_at, created_at=notice.created_at))
    return result


@business_boundary('work_task', 'write')
async def read_notification(session, actor, notification_id, payload):
    actor = await _identity(session, actor)
    try:
        notice_uuid = UUID(notification_id)
    except ValueError:
        raise AppException(ErrorCode.NOT_FOUND, "通知不存在", http_status=404) from None
    row = await session.scalar(select(WorkTaskNotification).where(WorkTaskNotification.id == notice_uuid,
        WorkTaskNotification.tenant_id == actor.tenant_id, WorkTaskNotification.recipient_id == actor.user_id).with_for_update())
    if not row:
        raise AppException(ErrorCode.NOT_FOUND, "通知不存在", http_status=404)
    task = await session.get(WorkTask, row.task_id)
    await _task(session, actor, task.task_id)
    batch = await session.get(WorkTaskBatch, task.batch_id)
    await _source_access(session, actor, batch)
    command, fresh = await _claim(session, actor, notification_id, "read_notification", payload)
    if fresh:
        _expect(task.version, payload.expected_version)
        row.read_at = datetime.now(timezone.utc)
        await idempotency_service.complete(session, command, {"read": True})
    return {"read": True}
