"""Owner-scoped document commands with immutable revisions and local confirmation."""
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import func, select

from ..core.context import get_trace_id
from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..models.agent_thread import AgentThread
from ..models.document_record import DocumentRecord
from ..models.document_draft_version import DocumentDraftVersion
from ..models.knowledge_source import KnowledgeSource
from ..models.knowledge_version import KnowledgeVersion
from ..models.knowledge_chunk import KnowledgeChunk
from ..schemas.command import CommandEnvelope
from ..schemas.document import DocumentInput, DocumentResponse, DocumentSummary, DocumentPage, DocumentVersion, DocumentTemplate, DocumentDraftDTO
from . import audit_service, idempotency_service, policy_service, degradation_service, document_generator
from .authorization_service import require_business_identity, require_permission, resource_clause, business_boundary
from .document_templates import TEMPLATES, check_document


async def _identity(session, actor):
    fresh = await require_business_identity(actor, session=session)
    require_permission(fresh, 'document', 'read')
    return fresh


def _actions(status):
    return {"CREATED": ["generate"], "DRAFT_READY": ["edit", "confirm", "reject", "regenerate"],
            "REVIEWING": ["edit", "confirm", "reject", "regenerate"], "PAUSED": ["retry"]}.get(status, [])


def _knowledge_scope(actor):
    now = datetime.now(timezone.utc)
    return [KnowledgeSource.tenant_id == actor.tenant_id,
            KnowledgeVersion.status == "published", KnowledgeVersion.parse_status == "READY",
            (KnowledgeVersion.effective_at.is_(None)) | (KnowledgeVersion.effective_at <= now),
            (KnowledgeVersion.expire_at.is_(None)) | (KnowledgeVersion.expire_at > now),
            (KnowledgeVersion.permission_tags == []) | KnowledgeVersion.permission_tags.overlap(actor.depts)]


async def _source_access(session, actor, sources):
    if actor.data_scope.get('identity_provider') == 'builtin':
        from .oa_graph_service import canonical_chunks
        from .authorization_service import require_fresh_identity
        knowledge = [item for item in sources if item.get('kind') == 'knowledge']
        if not knowledge:
            return
        actor = await require_fresh_identity(actor, session=session)
        require_permission(actor, 'knowledge', 'read')
        evidence = []
        for item in knowledge:
            reference = item.get('ref', '').split(':', 1)
            if (len(reference) != 2 or reference[0] != 'knowledge'
                    or not item.get('content_hash')
                    or sha256(item.get('content', '').encode()).hexdigest() != item['content_hash']):
                raise AppException(ErrorCode.FORBIDDEN, '文档引用来源已失效，请重新创建文档', http_status=403)
            evidence.append({**item, 'chunk_id': reference[1]})
        await canonical_chunks(session, actor, evidence)
        return
    ids = [UUID(item["version_id"]) for item in sources if item["kind"] == "knowledge"]
    if not ids:
        return
    found = set((await session.scalars(select(KnowledgeVersion.id).join(KnowledgeSource).where(
        KnowledgeVersion.id.in_(ids), *_knowledge_scope(actor)))).all())
    if found != set(ids):
        raise AppException(ErrorCode.FORBIDDEN, "文档引用来源权限已变化", http_status=403)


async def _owned(session, actor, document_id, *, lock=False):
    actor = await _identity(session, actor)
    query = select(DocumentRecord).where(DocumentRecord.document_id == document_id,
        DocumentRecord.tenant_id == actor.tenant_id, resource_clause(actor, 'document', DocumentRecord.owner_id, 'write' if lock else 'read'))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    record = await session.scalar(query)
    if record is None:
        raise AppException(ErrorCode.NOT_FOUND, "文档不存在", http_status=404)
    await _source_access(session, actor, record.source_snapshot)
    return record


async def _available(session, actor, record=None):
    if not await policy_service.is_scene_enabled(session, "document", actor.user_id,
            actor.depts[0] if actor.depts else "", actor.tenant_id):
        raise AppException(ErrorCode.DEGRADED, "文档智能路径已关闭", http_status=503)
    state = await degradation_service.resolve(session, scene="document", user=actor)
    if state:
        action = state.new_task_action if record is None or record.created_at >= state.created_at else state.inflight_action
        if action != "continue":
            raise AppException(ErrorCode.DEGRADED, "文档场景处于降级状态", http_status=503)


async def _claim(session, actor, resource_id, action, payload, key):
    return await idempotency_service.claim(session, CommandEnvelope(
        command_id=uuid4(), idempotency_key=key, actor_id=actor.user_id, tenant_id=actor.tenant_id,
        resource_type="document", resource_id=resource_id, trace_id=get_trace_id() or uuid4().hex,
        payload={"action": action, **payload}))


def _template(record):
    current = TEMPLATES[record.template_id]
    return DocumentTemplate(id=record.template_id, kind=current.kind, name=current.name,
                            version=record.template_version, sections=record.template_sections)


async def _version(session, record):
    return await session.scalar(select(DocumentDraftVersion).where(
        DocumentDraftVersion.document_id == record.id,
        DocumentDraftVersion.version == record.current_version)) if record.current_version else None


def _summary(record):
    return dict(document_id=record.document_id, thread_id=str(record.thread_id), subject=record.subject,
                status=record.status, version=record.current_version, available_actions=_actions(record.status),
                created_at=record.created_at, updated_at=record.updated_at)


async def _response(session, record):
    version = await _version(session, record)
    return DocumentResponse(**_summary(record), template=_template(record), recipient=record.recipient,
        deadline=record.deadline, classification=record.classification, distribution=record.distribution,
        sources=record.source_snapshot, draft={"body": version.body, "source_refs": version.source_refs} if version else None,
        checks=version.checks if version else [], confirmation=record.confirmation,
        error={"code": record.error_code, "trace_id": record.error_trace_id, "message": record.error_message}
        if record.status == "PAUSED" else None)


async def _event(session, record, actor, action, **summary):
    await audit_service.audit(session, f"document_{action}", thread_id=record.thread_id,
        business_id=record.document_id, actor_id=actor.user_id, target_type="document", target_id=record.document_id,
        input_summary=summary or None,
        output_summary={"status": record.status, "version": record.current_version, "external_writes": False})


async def _finish(session, record, command):
    thread = await session.get(AgentThread, record.thread_id)
    thread.status = {"CREATED": "DRAFT", "DRAFT_READY": "WAITING_HUMAN", "REVIEWING": "WAITING_HUMAN",
                     "PAUSED": "PAUSED", "CONFIRMED": "COMPLETED", "REJECTED": "REJECTED"}[record.status]
    thread.error_code, thread.error_msg = record.error_code, record.error_message
    # Dedicated workbenches own review; the generic scheduler has no graph interrupt here.
    thread.waiting_since = None
    await session.flush()
    await session.refresh(record)
    response = await _response(session, record)
    await idempotency_service.complete(session, command, response.model_dump(mode="json"))
    return response


def _expect(record, expected):
    if record.current_version != expected:
        raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "草稿版本已变化，请刷新后再操作", http_status=409)


def _reviewable(record):
    if record.status not in {"DRAFT_READY", "REVIEWING"}:
        raise AppException(ErrorCode.INVALID_STATE, "当前文档状态不可审阅", http_status=422)


def _validated_draft(record, draft):
    draft = DocumentDraftDTO.model_validate(draft)
    allowed = {item["ref"] for item in record.source_snapshot}
    if not set(draft.source_refs).issubset(allowed):
        raise AppException(ErrorCode.BAD_REQUEST, "草稿引用了无效来源", http_status=422)
    return draft


async def _persist(session, record, actor, draft, *, edited=False):
    draft = _validated_draft(record, draft)
    checks = [item.model_dump() for item in check_document(draft.body, _template(record))]
    version = DocumentDraftVersion(document_id=record.id, version=(record.current_version or 0) + 1,
        body=draft.body, source_refs=draft.source_refs, checks=checks, edited_by=actor.user_id if edited else None)
    session.add(version)
    record.current_version, record.status = version.version, "REVIEWING" if edited else "DRAFT_READY"
    record.error_code = record.error_trace_id = record.error_message = None
    await session.flush()


@business_boundary('document', 'write')
async def create_document(session, actor, payload):
    actor = await _identity(session, actor)
    data = payload.model_dump(exclude={"idempotency_key"})
    command, fresh = await _claim(session, actor, "create", "create", data, payload.idempotency_key)
    if not fresh:
        replay = DocumentResponse.model_validate(command.result)
        await _owned(session, actor, replay.document_id)
        return replay
    await _available(session, actor)
    public_id = f"DOC-{uuid4().hex[:12].upper()}"
    thread = AgentThread(tenant_id=actor.tenant_id, user_id=actor.user_id, scene="document",
                         intent="document", status="DRAFT", business_id=public_id)
    session.add(thread)
    await session.flush()
    text = "\n".join([payload.subject, payload.recipient, payload.basis, payload.key_points,
                      payload.deadline, payload.distribution])
    sources = [dict(ref="input:1", kind="input", title="提交材料", content=text,
                    content_hash=sha256(text.encode()).hexdigest(), source_location="input")]
    if payload.use_knowledge:
        from ..llm.base import LLMFactory
        formal = actor.data_scope.get('identity_provider') == 'builtin'
        if formal:
            require_permission(actor, 'knowledge', 'read')
        vectors = await asyncio.wait_for(LLMFactory.get_embedding().embed([payload.subject + " " + payload.key_points]), 20)
        actor = await _identity(session, actor)
        conditions = _knowledge_scope(actor)
        if formal:
            from .oa_scope_service import knowledge_binding_clause
            require_permission(actor, 'knowledge', 'read')
            conditions.append(knowledge_binding_clause(actor))
        distance = KnowledgeChunk.embedding.cosine_distance(vectors[0])
        rows = (await session.execute(select(KnowledgeChunk, KnowledgeVersion, KnowledgeSource)
            .join(KnowledgeVersion, KnowledgeChunk.version_id == KnowledgeVersion.id)
            .join(KnowledgeSource, KnowledgeVersion.source_id == KnowledgeSource.id)
            .where(*conditions, KnowledgeChunk.embedding.is_not(None))
            .order_by(distance, KnowledgeChunk.id).limit(5))).all()
        for chunk, version, source in rows:
            sources.append(dict(ref=f"knowledge:{chunk.id}", kind="knowledge", title=source.name,
                content=chunk.content, content_hash=sha256(chunk.content.encode()).hexdigest(),
                source_location=chunk.source_location or f"chunk:{chunk.chunk_index}",
                source_id=str(source.id), version_id=str(version.id), version=version.version))
    actor = await _identity(session, actor)
    await _source_access(session, actor, sources)
    template = TEMPLATES[payload.template_id]
    record = DocumentRecord(document_id=public_id, thread_id=thread.id, tenant_id=actor.tenant_id,
        owner_id=actor.user_id, template_id=template.id, template_version=template.version,
        template_sections=template.sections, input_snapshot=data, source_snapshot=sources,
        subject=payload.subject, recipient=payload.recipient, deadline=payload.deadline,
        classification=payload.classification, distribution=payload.distribution,
        idempotency_key=payload.idempotency_key, status="CREATED")
    session.add(record)
    await session.flush()
    await _event(session, record, actor, "created", input_hash=sha256(text.encode()).hexdigest())
    return await _finish(session, record, command)


@business_boundary('document', 'read')
async def get_document(session, actor, document_id):
    return await _response(session, await _owned(session, actor, document_id))


@business_boundary('document', 'read')
async def list_documents(session, actor, *, page=1, page_size=20):
    actor = await _identity(session, actor)
    page, page_size = max(1, page), min(100, max(1, page_size))
    query = select(DocumentRecord).where(DocumentRecord.tenant_id == actor.tenant_id, resource_clause(actor, 'document', DocumentRecord.owner_id))
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = (await session.scalars(query.order_by(DocumentRecord.updated_at.desc(), DocumentRecord.id)
                                    .offset((page - 1) * page_size).limit(page_size))).all()
    return DocumentPage(items=[DocumentSummary(**_summary(r)) for r in records], total=total, page=page, page_size=page_size)


@business_boundary('document', 'read')
async def list_versions(session, actor, document_id):
    record = await _owned(session, actor, document_id)
    versions = (await session.scalars(select(DocumentDraftVersion).where(DocumentDraftVersion.document_id == record.id)
                                     .order_by(DocumentDraftVersion.version))).all()
    return [DocumentVersion(version=v.version, draft={"body": v.body, "source_refs": v.source_refs},
                            checks=v.checks, edited_by=v.edited_by, created_at=v.created_at) for v in versions]


async def _generate(session, actor, record):
    try:
        payload = DocumentInput(**record.input_snapshot, idempotency_key=record.idempotency_key)
        draft = await asyncio.wait_for(document_generator.generate(payload, _template(record), record.source_snapshot), 25)
        draft = _validated_draft(record, draft)
    except Exception:
        actor = await _identity(session, actor)
        await _owned(session, actor, record.document_id, lock=True)
        record.status, record.error_code = "PAUSED", ErrorCode.DEPENDENCY_FAILED.value
        record.error_trace_id, record.error_message = get_trace_id(), "文档生成暂不可用，请重试"
        await _event(session, record, actor, "paused")
        return
    actor = await _identity(session, actor)
    await _owned(session, actor, record.document_id, lock=True)
    await _persist(session, record, actor, draft)


@business_boundary('document', 'write')
async def generate_draft(session, actor, document_id, payload, *, retry=False):
    actor = await _identity(session, actor)
    record = await _owned(session, actor, document_id, lock=True)
    command, fresh = await _claim(session, actor, document_id, "retry" if retry else "generate",
                                 payload.model_dump(exclude={"idempotency_key"}), payload.idempotency_key)
    if not fresh:
        return DocumentResponse.model_validate(command.result)
    await _available(session, actor, record)
    if record.status != ("PAUSED" if retry else "CREATED"):
        raise AppException(ErrorCode.INVALID_STATE, "当前状态不可生成", http_status=422)
    _expect(record, payload.expected_version)
    await _generate(session, actor, record)
    if record.status != "PAUSED":
        await _event(session, record, actor, "resumed" if retry else "generated")
    return await _finish(session, record, command)


@business_boundary('document', 'write')
async def save_draft(session, actor, document_id, payload):
    actor = await _identity(session, actor)
    record = await _owned(session, actor, document_id, lock=True)
    command, fresh = await _claim(session, actor, document_id, "edit",
        payload.model_dump(exclude={"idempotency_key"}), payload.idempotency_key)
    if not fresh:
        return DocumentResponse.model_validate(command.result)
    await _available(session, actor, record)
    _reviewable(record)
    _expect(record, payload.expected_version)
    await _persist(session, record, actor, payload.draft, edited=True)
    await _event(session, record, actor, "edited", draft_hash=idempotency_service.payload_digest(payload.draft.model_dump()))
    return await _finish(session, record, command)


@business_boundary('document', 'write')
async def decide(session, actor, document_id, payload):
    actor = await _identity(session, actor)
    record = await _owned(session, actor, document_id, lock=True)
    command, fresh = await _claim(session, actor, document_id, payload.action,
        payload.model_dump(exclude={"idempotency_key"}), payload.idempotency_key)
    if not fresh:
        return DocumentResponse.model_validate(command.result)
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
        checks = check_document(version.body, _template(record))
        if not payload.metadata_confirmed or any(c.severity == "error" for c in checks):
            raise AppException(ErrorCode.INVALID_STATE, "请确认发文元数据并修复格式错误", http_status=422)
        if any(c.severity == "warning" for c in checks) and not payload.warnings_acknowledged:
            raise AppException(ErrorCode.INVALID_STATE, "请确认敏感内容提示", http_status=422)
        record.status = "CONFIRMED"
        record.confirmation = {"version": version.version, "body_hash": sha256(version.body.encode()).hexdigest(),
            "actor_id": actor.user_id, "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "template_id": record.template_id, "template_version": record.template_version,
            "classification": record.classification, "distribution": record.distribution,
            "metadata_confirmed": True, "warnings_acknowledged": payload.warnings_acknowledged,
            "external_writes": False}
    if record.status != "PAUSED":
        await _event(session, record, actor, {"confirm": "confirmed", "reject": "rejected", "regenerate": "regenerated"}[payload.action],
                     reviewed_version=payload.expected_version,
                     reason_hash=sha256(payload.reason.encode()).hexdigest() if payload.reason else None)
    return await _finish(session, record, command)
