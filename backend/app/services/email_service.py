"""Atomic owner-scoped mail review; no send/forward/file-writing operations."""
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select

from ..core.context import get_trace_id
from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..models.agent_thread import AgentThread
from ..models.email_record import EmailRecord
from ..models.email_draft_version import EmailDraftVersion
from ..schemas.command import CommandEnvelope
from ..schemas.email import EmailInput, EmailDraftDTO, EmailResponse, EmailSummary, EmailPage, EmailVersion
from . import audit_service, idempotency_service, policy_service, degradation_service, email_generator
from .authorization_service import require_business_identity, require_permission, resource_clause, business_boundary


async def _identity(session, actor):
    fresh = await require_business_identity(actor, session=session)
    require_permission(fresh, 'email', 'read')
    return fresh


def _actions(status):
    return {"CREATED": ["analyze"], "DRAFT_READY": ["edit", "confirm", "reject", "regenerate"],
            "REVIEWING": ["edit", "confirm", "reject", "regenerate"], "PAUSED": ["retry"]}.get(status, [])


async def _owned(session, actor, email_id, *, lock=False):
    actor = await _identity(session, actor)
    query = select(EmailRecord).where(EmailRecord.email_id == email_id,
                                    EmailRecord.tenant_id == actor.tenant_id, resource_clause(actor, 'email', EmailRecord.owner_id, 'write' if lock else 'read'))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    record = await session.scalar(query)
    if record is None:
        raise AppException(ErrorCode.NOT_FOUND, "邮件不存在", http_status=404)
    return record


async def _available(session, actor, record=None):
    if not await policy_service.is_scene_enabled(session, "email", actor.user_id,
            actor.depts[0] if actor.depts else "", actor.tenant_id):
        raise AppException(ErrorCode.DEGRADED, "邮件智能路径已关闭", http_status=503)
    state = await degradation_service.resolve(session, scene="email", user=actor)
    if state:
        action = state.new_task_action if record is None or record.created_at >= state.created_at else state.inflight_action
        if action != "continue":
            raise AppException(ErrorCode.DEGRADED, "邮件场景处于降级状态", http_status=503)


async def _claim(session, actor, resource_id, action, payload, key):
    return await idempotency_service.claim(session, CommandEnvelope(
        command_id=uuid4(), idempotency_key=key, actor_id=actor.user_id, tenant_id=actor.tenant_id,
        resource_type="email", resource_id=resource_id, trace_id=get_trace_id() or uuid4().hex,
        payload={"action": action, **payload}))


def _input(record):
    return EmailInput(**record.input_snapshot, idempotency_key=record.idempotency_key)


def _secondary(payload):
    return payload.external_contact or any(item.sensitive for item in payload.attachments)


async def _version(session, record):
    return await session.scalar(select(EmailDraftVersion).where(EmailDraftVersion.email_id == record.id,
        EmailDraftVersion.version == record.current_version)) if record.current_version else None


def _summary(record):
    return dict(email_id=record.email_id, thread_id=str(record.thread_id), subject=record.subject,
        status=record.status, version=record.current_version, available_actions=_actions(record.status),
        created_at=record.created_at, updated_at=record.updated_at)


async def _response(session, record):
    version = await _version(session, record)
    payload = _input(record)
    return EmailResponse(**_summary(record), sender=payload.sender, recipients=payload.recipients,
        body=payload.body, external_contact=payload.external_contact, attachments=payload.attachments,
        sources=record.source_snapshot, draft=version.draft if version else None, checks=version.checks if version else [],
        secondary_confirmation_required=_secondary(payload), confirmation=record.confirmation,
        error={"code": record.error_code, "trace_id": record.error_trace_id, "message": record.error_message}
        if record.status == "PAUSED" else None)


async def _event(session, record, actor, action, **summary):
    await audit_service.audit(session, f"email_{action}", thread_id=record.thread_id,
        business_id=record.email_id, actor_id=actor.user_id, target_type="email", target_id=record.email_id,
        input_summary=summary or None,
        output_summary={"status": record.status, "version": record.current_version, "external_writes": False})


async def _finish(session, record, command):
    thread = await session.get(AgentThread, record.thread_id)
    thread.status = {"CREATED": "DRAFT", "DRAFT_READY": "WAITING_HUMAN", "REVIEWING": "WAITING_HUMAN",
                     "PAUSED": "PAUSED", "CONFIRMED": "COMPLETED", "REJECTED": "REJECTED"}[record.status]
    thread.error_code, thread.error_msg = record.error_code, record.error_message
    thread.waiting_since = None
    await session.flush()
    await session.refresh(record)
    response = await _response(session, record)
    await idempotency_service.complete(session, command, response.model_dump(mode="json"))
    return response


def _expect(record, expected):
    if record.current_version != expected:
        raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "回复草稿版本已变化，请刷新", http_status=409)


def _reviewable(record):
    if record.status not in {"DRAFT_READY", "REVIEWING"}:
        raise AppException(ErrorCode.INVALID_STATE, "当前邮件状态不可审阅", http_status=422)


def _validated_draft(record, data):
    draft = EmailDraftDTO.model_validate(data)
    allowed = {item["ref"] for item in record.source_snapshot}
    refs = set(draft.source_refs)
    for item in draft.action_items:
        refs.update(item.source_refs)
    if not refs.issubset(allowed):
        raise AppException(ErrorCode.BAD_REQUEST, "邮件草稿引用了无效来源", http_status=422)
    return draft


async def _persist(session, record, actor, data, *, edited=False):
    draft = _validated_draft(record, data)
    version = EmailDraftVersion(email_id=record.id, version=(record.current_version or 0) + 1,
        draft=draft.model_dump(), checks=email_generator.check_email(draft, _input(record)),
        edited_by=actor.user_id if edited else None)
    session.add(version)
    record.current_version, record.status = version.version, "REVIEWING" if edited else "DRAFT_READY"
    record.error_code = record.error_trace_id = record.error_message = None
    await session.flush()


@business_boundary('email', 'write')
async def create_email(session, actor, payload):
    actor = await _identity(session, actor)
    data = payload.model_dump(exclude={"idempotency_key"})
    command, fresh = await _claim(session, actor, "create", "create", data, payload.idempotency_key)
    if not fresh:
        replay = EmailResponse.model_validate(command.result)
        await _owned(session, actor, replay.email_id)
        return replay
    await _available(session, actor)
    public_id = f"MAIL-{uuid4().hex[:12].upper()}"
    thread = AgentThread(user_id=actor.user_id, tenant_id=actor.tenant_id, scene="email",
                         intent="email", status="DRAFT", business_id=public_id)
    session.add(thread)
    await session.flush()
    record = EmailRecord(email_id=public_id, thread_id=thread.id, tenant_id=actor.tenant_id,
        owner_id=actor.user_id, subject=payload.subject, input_snapshot=data,
        source_snapshot=email_generator.source_lines(payload.body), status="CREATED", idempotency_key=payload.idempotency_key)
    session.add(record)
    await session.flush()
    await _event(session, record, actor, "created", input_hash=idempotency_service.payload_digest(data))
    return await _finish(session, record, command)


@business_boundary('email', 'read')
async def get_email(session, actor, email_id):
    return await _response(session, await _owned(session, actor, email_id))


@business_boundary('email', 'read')
async def list_emails(session, actor, *, page=1, page_size=20):
    actor = await _identity(session, actor)
    page, page_size = max(1, page), min(100, max(1, page_size))
    query = select(EmailRecord).where(EmailRecord.tenant_id == actor.tenant_id, resource_clause(actor, 'email', EmailRecord.owner_id))
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = (await session.scalars(query.order_by(EmailRecord.updated_at.desc(), EmailRecord.id)
                                    .offset((page - 1) * page_size).limit(page_size))).all()
    return EmailPage(items=[EmailSummary(**_summary(r)) for r in records], total=total, page=page, page_size=page_size)


@business_boundary('email', 'read')
async def list_versions(session, actor, email_id):
    record = await _owned(session, actor, email_id)
    versions = (await session.scalars(select(EmailDraftVersion).where(EmailDraftVersion.email_id == record.id)
                                     .order_by(EmailDraftVersion.version))).all()
    return [EmailVersion(version=v.version, draft=v.draft, checks=v.checks,
                         edited_by=v.edited_by, created_at=v.created_at) for v in versions]


async def _generate(session, actor, record):
    try:
        draft = await asyncio.wait_for(email_generator.generate(_input(record), record.source_snapshot), 25)
        draft = _validated_draft(record, draft)
    except Exception:
        actor = await _identity(session, actor)
        await _owned(session, actor, record.email_id, lock=True)
        record.status, record.error_code = "PAUSED", ErrorCode.DEPENDENCY_FAILED.value
        record.error_trace_id, record.error_message = get_trace_id(), "邮件分析暂不可用，请重试"
        await _event(session, record, actor, "paused")
        return
    actor = await _identity(session, actor)
    await _owned(session, actor, record.email_id, lock=True)
    await _persist(session, record, actor, draft)


@business_boundary('email', 'write')
async def analyze(session, actor, email_id, payload, *, retry=False):
    actor = await _identity(session, actor)
    record = await _owned(session, actor, email_id, lock=True)
    command, fresh = await _claim(session, actor, email_id, "retry" if retry else "analyze",
                                 payload.model_dump(exclude={"idempotency_key"}), payload.idempotency_key)
    if not fresh:
        return EmailResponse.model_validate(command.result)
    await _available(session, actor, record)
    if record.status != ("PAUSED" if retry else "CREATED"):
        raise AppException(ErrorCode.INVALID_STATE, "当前邮件状态不可分析", http_status=422)
    _expect(record, payload.expected_version)
    await _generate(session, actor, record)
    if record.status != "PAUSED":
        await _event(session, record, actor, "resumed" if retry else "analyzed")
    return await _finish(session, record, command)


@business_boundary('email', 'write')
async def save_draft(session, actor, email_id, payload):
    actor = await _identity(session, actor)
    record = await _owned(session, actor, email_id, lock=True)
    command, fresh = await _claim(session, actor, email_id, "edit",
        payload.model_dump(exclude={"idempotency_key"}), payload.idempotency_key)
    if not fresh:
        return EmailResponse.model_validate(command.result)
    await _available(session, actor, record)
    _reviewable(record)
    _expect(record, payload.expected_version)
    await _persist(session, record, actor, payload.draft, edited=True)
    await _event(session, record, actor, "edited", draft_hash=idempotency_service.payload_digest(payload.draft.model_dump()))
    return await _finish(session, record, command)


@business_boundary('email', 'write')
async def decide(session, actor, email_id, payload):
    actor = await _identity(session, actor)
    record = await _owned(session, actor, email_id, lock=True)
    command, fresh = await _claim(session, actor, email_id, payload.action,
        payload.model_dump(exclude={"idempotency_key"}), payload.idempotency_key)
    if not fresh:
        return EmailResponse.model_validate(command.result)
    await _available(session, actor, record)
    _reviewable(record)
    _expect(record, payload.expected_version)
    version = await _version(session, record)
    if payload.action == "regenerate":
        await _generate(session, actor, record)
    elif payload.action == "reject":
        if not payload.reason or not payload.reason.strip():
            raise AppException(ErrorCode.BAD_REQUEST, "请填写拒绝原因", http_status=422)
        record.status = "REJECTED"
    else:
        checks = email_generator.check_email(EmailDraftDTO.model_validate(version.draft), _input(record))
        if not payload.metadata_confirmed or any(c["severity"] == "error" for c in checks):
            raise AppException(ErrorCode.INVALID_STATE, "请核对收件人和修复回复草稿", http_status=422)
        if any(c["severity"] == "warning" for c in checks) and not payload.warnings_acknowledged:
            raise AppException(ErrorCode.INVALID_STATE, "请确认邮件敏感提示", http_status=422)
        if _secondary(_input(record)) and not payload.secondary_confirmed:
            raise AppException(ErrorCode.INVALID_STATE, "外部联系人或敏感附件需要二次确认", http_status=422)
        record.status = "CONFIRMED"
        record.confirmation = {"version": version.version, "actor_id": actor.user_id,
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "draft_hash": idempotency_service.payload_digest(version.draft),
            "metadata_confirmed": True, "warnings_acknowledged": payload.warnings_acknowledged,
            "secondary_confirmed": payload.secondary_confirmed, "external_writes": False}
    if record.status != "PAUSED":
        await _event(session, record, actor, {"confirm": "confirmed", "reject": "rejected", "regenerate": "regenerated"}[payload.action],
                     reviewed_version=payload.expected_version,
                     reason_hash=sha256(payload.reason.encode()).hexdigest() if payload.reason else None)
    return await _finish(session, record, command)
