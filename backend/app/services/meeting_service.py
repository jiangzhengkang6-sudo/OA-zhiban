"""Authorized, versioned meeting commands with atomic platform-only results."""

from collections.abc import Iterable
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.context import CurrentUser, get_trace_id, set_trace_id
from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..graph.graph_service import runtime, extract_interrupt
from ..models.agent_thread import AgentThread
from ..models.idempotency_record import IdempotencyRecord
from ..models.meeting_decision import MeetingDecision
from ..models.meeting_draft_version import MeetingDraftVersion
from ..models.meeting_record import MeetingRecord
from ..models.meeting_segment import MeetingSegment
from ..models.meeting_source import MeetingSource
from ..schemas.command import CommandEnvelope
from ..schemas.meeting import (
    MeetingDraftDTO, MeetingInput, MeetingPage, MeetingResponse,
    MeetingSegmentDTO, MeetingSummary,
)
from . import audit_service, degradation_service, idempotency_service, policy_service, runtime_trace_service
from .authorization_service import require_business_identity, require_permission, resource_clause, business_boundary
from .meeting_parser import MeetingParser


class MeetingStateError(ValueError):
    """A meeting draft cannot perform the requested transition."""


def validate_draft(draft: dict) -> dict:
    if not isinstance(draft, dict):
        raise ValueError("会议草稿必须是对象")
    if not str(draft.get("summary", "")).strip():
        raise ValueError("纪要摘要不能为空")
    for field in ("decisions", "action_items"):
        for item in draft.get(field, []) or []:
            if not isinstance(item, dict) or not item.get("source_refs"):
                raise ValueError(f"{field}必须包含来源片段")
    validated = MeetingDraftDTO.model_validate(draft).model_dump()
    for item in validated["action_items"]:
        if not item["assignee_candidate"] or not item["due_at_candidate"]:
            item["needs_confirmation"] = True
    return validated


def next_draft_version(existing_versions: Iterable[int]) -> int:
    return max((int(value) for value in existing_versions), default=0) + 1


def apply_decision(status: str, action: str, reason: str | None) -> str:
    if status not in {"DRAFT_READY", "REVIEWING"}:
        raise MeetingStateError("当前会议草稿状态不可处理")
    if action == "confirm":
        return "CONFIRMED"
    if action == "reject":
        if not reason or not reason.strip():
            raise MeetingStateError("拒绝原因不能为空")
        return "REJECTED"
    if action == "regenerate":
        return "DRAFT_READY"
    raise MeetingStateError("不支持的会议决定动作")


async def _identity(session, actor: CurrentUser) -> CurrentUser:
    fresh = await require_business_identity(actor, session=session)
    require_permission(fresh, 'meeting', 'read')
    return fresh


async def _scene_available(session: AsyncSession, actor: CurrentUser, record: MeetingRecord | None = None) -> None:
    """Apply the same live meeting switch before starting business work."""
    if not await policy_service.is_scene_enabled(
        session, "meeting", actor.user_id, actor.depts[0] if actor.depts else "", actor.tenant_id
    ):
        raise AppException(ErrorCode.DEGRADED, "会议智能路径已关闭，请稍后重试", http_status=503)
    state = await degradation_service.resolve(session, scene="meeting", user=actor)
    if state is None:
        return
    action = state.new_task_action if record is None or record.created_at >= state.created_at else state.inflight_action
    if action != "continue":
        raise AppException(ErrorCode.DEGRADED, "会议场景处于降级状态，请稍后重试", http_status=503)


def _actions(status: str) -> list[str]:
    return {
        "CREATED": ["generate"],
        "DRAFT_READY": ["edit", "confirm", "reject", "regenerate"],
        "REVIEWING": ["edit", "confirm", "reject", "regenerate"],
        "PAUSED": ["retry"],
    }.get(status, [])


async def _owned(session: AsyncSession, actor: CurrentUser, meeting_id: str, *, lock: bool = False) -> MeetingRecord:
    actor = await _identity(session, actor)
    query = select(MeetingRecord).where(
        MeetingRecord.meeting_id == meeting_id,
        MeetingRecord.tenant_id == actor.tenant_id,
        resource_clause(actor, 'meeting', MeetingRecord.owner_id, 'write' if lock else 'read'),
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    record = await session.scalar(query)
    if record is None:
        raise AppException(ErrorCode.NOT_FOUND, "会议不存在", http_status=404)
    return record


async def _claim(session, actor, resource_id: str, action: str, payload: dict, key: str):
    trace_id = get_trace_id() or uuid4().hex
    if not get_trace_id():
        set_trace_id(trace_id)
    envelope = CommandEnvelope(
        command_id=uuid4(), idempotency_key=key, actor_id=actor.user_id,
        tenant_id=actor.tenant_id, resource_type="meeting", resource_id=resource_id,
        trace_id=trace_id, payload={"action": action, **payload},
    )
    return await idempotency_service.claim(session, envelope)


async def _segments(session, record) -> list[MeetingSegment]:
    return list((await session.scalars(select(MeetingSegment).where(
        MeetingSegment.meeting_id == record.id).order_by(MeetingSegment.ordinal))).all())


def _segment_dto(segment: MeetingSegment) -> MeetingSegmentDTO:
    return MeetingSegmentDTO(
        segment_id=str(segment.id), ordinal=segment.ordinal,
        start_offset=segment.start_offset, end_offset=segment.end_offset, text=segment.text,
        locator=f"chars:{segment.start_offset}-{segment.end_offset}",
        text_hash=segment.text_hash, summary=segment.summary,
    )


async def _version(session, record):
    if record.current_version is None:
        return None
    return await session.scalar(select(MeetingDraftVersion).where(
        MeetingDraftVersion.meeting_id == record.id,
        MeetingDraftVersion.version == record.current_version))


def _draft_dto(version) -> MeetingDraftDTO | None:
    if version is None:
        return None
    return MeetingDraftDTO(
        summary=version.summary, topics=version.topics or [], decisions=version.decisions or [],
        action_items=version.action_items or [], source_refs=version.source_refs or [])


async def _response(session, record) -> MeetingResponse:
    return MeetingResponse(
        meeting_id=record.meeting_id, thread_id=str(record.thread_id) if record.thread_id else None,
        status=record.status, title=record.title, version=record.current_version,
        segments=[_segment_dto(item) for item in await _segments(session, record)],
        draft=_draft_dto(await _version(session, record)),
        available_actions=_actions(record.status), trace_id=get_trace_id(),
        created_at=record.created_at, updated_at=record.updated_at,
    )


async def _event(session, record, actor, action: str, *, input_summary=None):
    await audit_service.audit(
        session, action, thread_id=record.thread_id, business_id=record.meeting_id,
        actor_id=actor.user_id, target_type="meeting", target_id=record.meeting_id,
        input_summary=input_summary,
        output_summary={"status": record.status, "version": record.current_version, "external_writes": False},
        result="fail" if action == "meeting_paused" else "success",
        error_code=record.error_code if action == "meeting_paused" else None,
    )


async def _sync_thread(session, record):
    thread = await session.get(AgentThread, record.thread_id)
    thread.status = {
        "CREATED": "DRAFT", "PROCESSING": "PRECHECK", "DRAFT_READY": "WAITING_HUMAN",
        "REVIEWING": "WAITING_HUMAN", "PAUSED": "PAUSED",
        "CONFIRMED": "COMPLETED", "REJECTED": "REJECTED",
    }[record.status]
    thread.error_code = record.error_code
    thread.error_msg = record.error_message
    if runtime.ready:
        pending = extract_interrupt(await runtime.get_state(record.thread_id))
        thread.current_interrupt_id = pending[0] if pending and record.status in {"DRAFT_READY", "REVIEWING"} else None
    thread.waiting_since = (thread.waiting_since or datetime.now(timezone.utc)) if thread.status == "WAITING_HUMAN" else None


async def _finish(session, record, command) -> MeetingResponse:
    await _sync_thread(session, record)
    await session.flush()
    await session.refresh(record)
    response = await _response(session, record)
    # No external effects: claim, business state, audit and result commit together.
    await idempotency_service.complete(session, command, response.model_dump(mode="json"))
    return response


def _expect_version(record, expected_version):
    if expected_version is not None and record.current_version != expected_version:
        raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "草稿版本已变化，请刷新后再操作", http_status=409)


async def _persist_draft(session, record, actor, draft_data, status):
    draft_data = validate_draft(draft_data)
    allowed = {str(item.id) for item in await _segments(session, record)}
    refs = set(draft_data["source_refs"])
    for item in [*draft_data["decisions"], *draft_data["action_items"]]:
        refs.update(item["source_refs"])
    if not draft_data["source_refs"] or not refs.issubset(allowed):
        raise AppException(ErrorCode.BAD_REQUEST, "草稿来源片段无效", http_status=400)
    version = MeetingDraftVersion(
        meeting_id=record.id, version=(record.current_version or 0) + 1,
        status=status, **draft_data, edited_by=actor.user_id if status == "REVIEWING" else None,
    )
    session.add(version)
    record.current_version = version.version
    record.status = status
    await session.flush()
    return version


def _command_key(command) -> str:
    return idempotency_service.payload_digest({
        "actor": command.actor_id, "resource": command.resource_id,
        "key": command.idempotency_key, "payload_hash": command.payload_hash,
    })


async def _run_generation(session, record, actor, command, *, retry=False, regenerate=False):
    """Reconcile a durable graph result before repeating a pure generator call."""
    started = datetime.now(timezone.utc)
    record.status = "PROCESSING"
    token = _command_key(command)
    try:
        snapshot = await runtime.get_state(record.thread_id)
        values = snapshot.values or {}
        if values.get("meeting_command_key") == token and values.get("draft"):
            # A review node can fail after generation when authority changes.
            # Resume that pending node before exposing the cached draft.
            result = await runtime.invoke(record.thread_id, None) if snapshot.next and not extract_interrupt(snapshot) else values
        elif retry and snapshot.next:
            result = await runtime.invoke(record.thread_id, None)
        elif regenerate and values.get("meeting_command_key") == token and snapshot.next:
            result = await runtime.invoke(record.thread_id, None)
        elif regenerate:
            if not extract_interrupt(snapshot):
                raise AppException(ErrorCode.INVALID_STATE, "会议审阅恢复点不可用，请刷新任务", http_status=409)
            result = await runtime.resume(record.thread_id, {
                "action": "regenerate", "command_key": token, "version": (record.current_version or 0) + 1,
            })
        else:
            result = await runtime.invoke(record.thread_id, {
                "thread_id": str(record.thread_id), "user_id": actor.user_id,
                "tenant_id": actor.tenant_id, "scene": "meeting", "intent": "meeting",
                "business_id": record.meeting_id, "trace_id": get_trace_id(),
                "segments": [_segment_dto(item).model_dump() for item in await _segments(session, record)],
                "draft": None, "meeting_version": (record.current_version or 0) + 1,
                "meeting_command_key": token, "meeting_generation_action": "generate",
                "meeting_decision_key": "", "error": None,
            })
        await _owned(session, actor, record.meeting_id, lock=True)
        draft = validate_draft(result["draft"])
    except AppException as exc:
        if exc.http_status in {401, 403, 404, 409, 422}:
            raise
        await _pause_generation(session, record, actor, started)
        return None
    except Exception:
        await _pause_generation(session, record, actor, started)
        return None
    record.error_code = record.error_message = record.error_trace_id = None
    await runtime_trace_service.record_span(
        session, tenant_id=record.tenant_id, trace_id=get_trace_id(), thread_id=record.thread_id,
        node_name="meeting_generate", tool_name=None, started_at=started,
        finished_at=datetime.now(timezone.utc), status="success",
    )
    return draft


async def _pause_generation(session, record, actor, started):
    await _owned(session, actor, record.meeting_id, lock=True)
    record.status = "PAUSED"
    record.error_code = ErrorCode.DEPENDENCY_FAILED.value
    # Keep the first pause trace as the durable retry attempt token. A retry
    # that fails must remain replayable when the client omits its key.
    if not record.error_trace_id:
        record.error_trace_id = get_trace_id()
    record.error_message = "会议生成暂不可用，请从恢复点重试"
    await runtime_trace_service.record_span(
        session, tenant_id=record.tenant_id, trace_id=get_trace_id(), thread_id=record.thread_id,
        node_name="meeting_generate", tool_name=None, started_at=started,
        finished_at=datetime.now(timezone.utc), status="error", error_code=record.error_code,
    )
    await _event(session, record, actor, "meeting_paused")


async def _resume_decision(record, command, action, draft):
    snapshot = await runtime.get_state(record.thread_id)
    token = _command_key(command)
    if snapshot.values.get("meeting_decision_key") == token:
        return
    if not extract_interrupt(snapshot):
        raise AppException(ErrorCode.INVALID_STATE, "会议审阅恢复点不可用，请刷新任务", http_status=409)
    await runtime.resume(record.thread_id, {
        "action": action, "command_key": token, "version": record.current_version,
        "draft": _draft_dto(draft).model_dump(),
    })


@business_boundary('meeting', 'write')
async def create_meeting(session: AsyncSession, actor: CurrentUser, payload: MeetingInput) -> MeetingResponse:
    actor = await _identity(session, actor)
    segments = MeetingParser().parse(payload.content)
    business_payload = {"title": payload.title, "content": payload.content, "source_type": payload.source_type}
    key = payload.idempotency_key or idempotency_service.payload_digest(business_payload)
    command, fresh = await _claim(session, actor, "create", "create", business_payload, key)
    if not fresh:
        return MeetingResponse.model_validate(command.result)
    await _scene_available(session, actor)
    public_id = f"MTG-{uuid4().hex[:12].upper()}"
    thread = AgentThread(user_id=actor.user_id, tenant_id=actor.tenant_id,
                         scene="meeting", intent="meeting", status="DRAFT", business_id=public_id)
    session.add(thread)
    await session.flush()
    record = MeetingRecord(
        meeting_id=public_id, thread_id=thread.id, tenant_id=actor.tenant_id,
        owner_id=actor.user_id, title=payload.title, status="CREATED",
        idempotency_key=idempotency_service.payload_digest({"actor": actor.user_id, "key": key}),
    )
    session.add(record)
    await session.flush()
    digest = sha256(payload.content.encode("utf-8")).hexdigest()
    source = MeetingSource(meeting_id=record.id, source_type=payload.source_type,
                           content_hash=digest, storage_ref=f"db://meeting/{public_id}",
                           content_length=len(payload.content))
    session.add(source)
    await session.flush()
    session.add_all([
        MeetingSegment(meeting_id=record.id, source_id=source.id, ordinal=item.ordinal,
                       start_offset=item.start_offset, end_offset=item.end_offset, text=item.text,
                       text_hash=item.text_hash, locator={"chars": [item.start_offset, item.end_offset]},
                       summary=item.summary) for item in segments
    ])
    await _event(session, record, actor, "meeting_created",
                 input_summary={"content_hash": digest, "content_length": len(payload.content)})
    await _event(session, record, actor, "meeting_parsed", input_summary={"segment_count": len(segments)})
    return await _finish(session, record, command)


@business_boundary('meeting', 'read')
async def get_meeting(session: AsyncSession, actor: CurrentUser, meeting_id: str) -> MeetingResponse:
    return await _response(session, await _owned(session, actor, meeting_id))


@business_boundary('meeting', 'read')
async def list_meetings(session: AsyncSession, actor: CurrentUser, *, page=1, page_size=20) -> MeetingPage:
    actor = await _identity(session, actor)
    page, page_size = max(page, 1), min(max(page_size, 1), 100)
    query = select(MeetingRecord).where(MeetingRecord.tenant_id == actor.tenant_id,
                                       resource_clause(actor, 'meeting', MeetingRecord.owner_id))
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = (await session.scalars(query.order_by(MeetingRecord.updated_at.desc(), MeetingRecord.id)
                                    .offset((page - 1) * page_size).limit(page_size))).all()
    return MeetingPage(items=[MeetingSummary(
        meeting_id=item.meeting_id, thread_id=str(item.thread_id), title=item.title,
        status=item.status, version=item.current_version, available_actions=_actions(item.status),
        created_at=item.created_at, updated_at=item.updated_at,
    ) for item in records], total=total, page=page, page_size=page_size)


@business_boundary('meeting', 'write')
async def generate_draft(session: AsyncSession, actor: CurrentUser, meeting_id: str,
                         idempotency_key=None, expected_version=None, *, retry=False) -> MeetingResponse:
    actor = await _identity(session, actor)
    record = await _owned(session, actor, meeting_id, lock=True)
    action = "retry" if retry else "generate"
    key = idempotency_key
    if key is None and retry:
        if record.status == "PAUSED":
            key = f"retry:auto:{record.error_trace_id}"
        else:
            # The error is cleared after recovery. Use the durable original
            # command so a transport replay still returns its exact snapshot.
            previous = await session.scalar(select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == actor.tenant_id,
                IdempotencyRecord.actor_id == actor.user_id,
                IdempotencyRecord.resource_type == "meeting",
                IdempotencyRecord.resource_id == meeting_id,
                IdempotencyRecord.idempotency_key.startswith("retry:auto:"),
                IdempotencyRecord.status == "SUCCEEDED",
            ).order_by(IdempotencyRecord.created_at.desc()).limit(1))
            key = previous.idempotency_key if previous else "retry:auto:none"
    key = key or "generate:initial"
    command, fresh = await _claim(session, actor, meeting_id, action,
                                 {"expected_version": expected_version}, key)
    if not fresh:
        return MeetingResponse.model_validate(command.result)
    await _scene_available(session, actor, record)
    if record.status != ("PAUSED" if retry else "CREATED"):
        raise AppException(ErrorCode.INVALID_STATE, "当前会议状态不可生成草稿", http_status=422)
    _expect_version(record, expected_version)
    draft_data = await _run_generation(session, record, actor, command, retry=retry)
    if draft_data is not None:
        await _persist_draft(session, record, actor, draft_data, "DRAFT_READY")
        if retry:
            await _event(session, record, actor, "meeting_resumed")
        snapshot = await runtime.get_state(record.thread_id)
        event = "meeting_regenerated" if snapshot.values.get("meeting_generation_action") == "regenerate" else "meeting_generated"
        await _event(session, record, actor, event)
    return await _finish(session, record, command)


@business_boundary('meeting', 'write')
async def save_draft(session: AsyncSession, actor: CurrentUser, meeting_id: str,
                     draft_data: dict, idempotency_key=None, expected_version=None) -> MeetingResponse:
    actor = await _identity(session, actor)
    record = await _owned(session, actor, meeting_id, lock=True)
    payload = {"draft": draft_data, "expected_version": expected_version}
    key = idempotency_key or idempotency_service.payload_digest(payload)
    command, fresh = await _claim(session, actor, meeting_id, "edit", payload, key)
    if not fresh:
        return MeetingResponse.model_validate(command.result)
    await _scene_available(session, actor, record)
    if record.status not in {"DRAFT_READY", "REVIEWING"}:
        raise AppException(ErrorCode.INVALID_STATE, "当前会议状态不可编辑", http_status=422)
    _expect_version(record, expected_version)
    await _persist_draft(session, record, actor, draft_data, "REVIEWING")
    await runtime.update_state(record.thread_id, {"draft": validate_draft(draft_data),
                                                "meeting_version": record.current_version,
                                                "meeting_status": "REVIEWING",
                                                "next_action": "review", "meeting_decision_key": ""},
                               as_node="meeting")
    # Updating a checkpoint replaces pending tasks. Re-enter the pure review
    # node to publish the new version's interrupt without generating again.
    await runtime.invoke(record.thread_id, None)
    await _owned(session, actor, meeting_id, lock=True)
    await _event(session, record, actor, "meeting_edited",
                 input_summary={"draft_hash": idempotency_service.payload_digest(draft_data)})
    return await _finish(session, record, command)


@business_boundary('meeting', 'write')
async def decide(session: AsyncSession, actor: CurrentUser, meeting_id: str, action: str,
                 reason: str | None, idempotency_key: str, expected_version=None) -> MeetingResponse:
    actor = await _identity(session, actor)
    record = await _owned(session, actor, meeting_id, lock=True)
    payload = {"reason": reason, "expected_version": expected_version}
    command, fresh = await _claim(session, actor, meeting_id, action, payload, idempotency_key)
    if not fresh:
        return MeetingResponse.model_validate(command.result)
    await _scene_available(session, actor, record)
    try:
        next_status = apply_decision(record.status, action, reason)
    except MeetingStateError as exc:
        raise AppException(ErrorCode.INVALID_STATE, str(exc), http_status=422) from exc
    _expect_version(record, expected_version)
    reviewed = await _version(session, record)
    if reviewed is None:
        raise AppException(ErrorCode.INVALID_STATE, "会议没有可审阅草稿", http_status=422)
    decision = MeetingDecision(
        meeting_id=record.id, draft_version_id=reviewed.id, actor_id=actor.user_id,
        action=action, reason=reason, idempotency_key=idempotency_key,
        payload_hash=command.payload_hash, result={}, trace_id=get_trace_id(),
    )
    session.add(decision)
    if action == "regenerate":
        draft_data = await _run_generation(session, record, actor, command, regenerate=True)
        if draft_data is not None:
            await _persist_draft(session, record, actor, draft_data, next_status)
    else:
        await _resume_decision(record, command, action, reviewed)
        await _owned(session, actor, meeting_id, lock=True)
        record.status = next_status
    if record.status != "PAUSED":
        await _event(session, record, actor, {"confirm": "meeting_confirmed", "reject": "meeting_rejected",
                                            "regenerate": "meeting_regenerated"}[action],
                     input_summary={"reviewed_version": reviewed.version,
                                    "reason_hash": sha256(reason.encode()).hexdigest() if reason else None})
    response = await _finish(session, record, command)
    decision.result = response.model_dump(mode="json")
    await session.flush()
    return response
