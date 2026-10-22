"""Human-approved report plans, immutable query evidence and local publication."""
from datetime import datetime, timezone
from copy import deepcopy
from uuid import uuid4

from sqlalchemy import func, select

from ..core.context import get_trace_id
from ..core.config import get_settings
from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..models.agent_thread import AgentThread
from ..models.report_record import ReportRecord, ReportVersion
from ..schemas.command import CommandEnvelope
from ..schemas.report import ReportPlan, ReportResponse, ReportSummary, ReportVersionDTO, ReportPage
from . import audit_service, idempotency_service, policy_service, degradation_service, report_generator, report_query, runtime_trace_service
from .authorization_service import require_business_identity, require_permission, resource_clause, business_boundary


async def _identity(session, actor):
    fresh = await require_business_identity(actor, session=session)
    require_permission(fresh, 'report', 'read')
    return fresh


async def _scope(session, actor, record, snapshot=None):
    plan = ReportPlan.model_validate(record.plan)
    if report_query.scope_fingerprint(actor, plan.scope) != record.scope_fingerprint:
        raise AppException(ErrorCode.FORBIDDEN, "统计范围权限已变化，请重新创建并确认计划", http_status=403)
    if plan.metric_version != 1:
        raise AppException(ErrorCode.INVALID_STATE, "指标版本已变化，请重新确认计划", http_status=409)
    await report_query.validate_snapshot_scope(session, actor, plan, snapshot if snapshot is not None else record.cached_snapshot)


async def _owned(session, actor, report_id, *, lock=False):
    actor = await _identity(session, actor)
    query = select(ReportRecord).where(ReportRecord.report_id == report_id,
        ReportRecord.tenant_id == actor.tenant_id, resource_clause(actor, 'report', ReportRecord.owner_id, 'write' if lock else 'read'))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    record = await session.scalar(query)
    if record is None:
        raise AppException(ErrorCode.NOT_FOUND, "报表不存在", http_status=404)
    await _scope(session, actor, record)
    return record


async def _available(session, actor, record=None):
    if not await policy_service.is_scene_enabled(session, "report", actor.user_id,
            actor.depts[0] if actor.depts else "", actor.tenant_id):
        raise AppException(ErrorCode.DEGRADED, "报表智能路径已关闭", http_status=503)
    state = await degradation_service.resolve(session, scene="report", user=actor)
    if state:
        action = state.new_task_action if record is None or record.created_at >= state.created_at else state.inflight_action
        if action != "continue":
            raise AppException(ErrorCode.DEGRADED, "报表场景处于降级状态", http_status=503)


def _actions(status):
    return {"PLAN_READY": ["approve"], "DRAFT_READY": ["edit", "publish"],
            "REVIEWING": ["edit", "publish"], "PAUSED": ["retry"]}.get(status, [])


def _summary(record):
    return dict(report_id=record.report_id, thread_id=str(record.thread_id), subject=record.subject,
        status=record.status, version=record.current_version, available_actions=_actions(record.status),
        created_at=record.created_at, updated_at=record.updated_at)


async def _response(session, record):
    version = await session.scalar(select(ReportVersion).where(ReportVersion.report_id == record.id,
        ReportVersion.version == record.current_version))
    return ReportResponse(**_summary(record), plan=record.plan, plan_confirmation=record.plan_confirmation,
        snapshot=_public_snapshot(version.snapshot if version else record.cached_snapshot),
        draft=version.draft if version else None, publication=record.publication,
        error={"code": record.error_code, "trace_id": record.error_trace_id, "message": record.error_message}
        if record.status == "PAUSED" else None)


def _public_snapshot(snapshot):
    if snapshot is None:
        return None
    result = deepcopy(snapshot)
    for metric in result["metrics"]:
        metric.pop("source_ids", None)
    return result


async def _claim(session, actor, resource_id, action, payload):
    return await idempotency_service.claim(session, CommandEnvelope(command_id=uuid4(),
        idempotency_key=payload.idempotency_key, actor_id=actor.user_id, tenant_id=actor.tenant_id,
        resource_type="report", resource_id=resource_id, trace_id=get_trace_id() or uuid4().hex,
        payload={"action": action, **payload.model_dump(mode="json", exclude={"idempotency_key"})}))


async def _event(session, actor, record, action):
    await audit_service.audit(session, f"report_{action}", thread_id=record.thread_id,
        business_id=record.report_id, actor_id=actor.user_id, target_type="report", target_id=record.report_id,
        output_summary={"version": record.current_version, "status": record.status,
            "plan_hash": idempotency_service.payload_digest(record.plan), "external_writes": False})


async def _finish(session, actor, record, command, action):
    thread = await session.get(AgentThread, record.thread_id)
    thread.status = {"PLAN_READY": "WAITING_HUMAN", "DRAFT_READY": "WAITING_HUMAN",
        "REVIEWING": "WAITING_HUMAN", "PAUSED": "PAUSED", "PUBLISHED": "COMPLETED"}[record.status]
    thread.waiting_since = None
    thread.error_code, thread.error_msg = record.error_code, record.error_message
    await _event(session, actor, record, action)
    await session.flush()
    await session.refresh(record)
    response = await _response(session, record)
    await idempotency_service.complete(session, command, response.model_dump(mode="json"))
    return response


async def _replay(session, actor, record, command):
    response = ReportResponse.model_validate(command.result)
    await _scope(session, actor, record)
    return response


def _expect(record, payload):
    if record.current_version != payload.expected_version:
        raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "报表版本已变化，请刷新", http_status=409)


@business_boundary('report', 'write')
async def create_report(session, actor, payload):
    actor = await _identity(session, actor)
    scope = report_query.scope_fingerprint(actor, payload.plan.scope)
    command, fresh = await _claim(session, actor, "create", "create", payload)
    if not fresh:
        record = await _owned(session, actor, command.result["report_id"])
        return await _replay(session, actor, record, command)
    await _available(session, actor)
    public_id = f"RPT-{uuid4().hex[:12].upper()}"
    thread = AgentThread(tenant_id=actor.tenant_id, user_id=actor.user_id, scene="report",
        intent="report", status="WAITING_HUMAN", business_id=public_id)
    session.add(thread)
    await session.flush()
    record = ReportRecord(report_id=public_id, thread_id=thread.id, tenant_id=actor.tenant_id,
        owner_id=actor.user_id, subject=payload.subject, plan=payload.plan.model_dump(mode="json"),
        scope_fingerprint=scope, status="PLAN_READY", current_version=1, idempotency_key=payload.idempotency_key)
    session.add(record)
    await session.flush()
    return await _finish(session, actor, record, command, "created")


@business_boundary('report', 'read')
async def get_report(session, actor, report_id):
    return await _response(session, await _owned(session, actor, report_id))


@business_boundary('report', 'read')
async def list_reports(session, actor, *, page=1, page_size=20):
    actor = await _identity(session, actor)
    page, page_size = max(1, page), min(100, max(1, page_size))
    query = select(ReportRecord).where(ReportRecord.tenant_id == actor.tenant_id, resource_clause(actor, 'report', ReportRecord.owner_id))
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (await session.scalars(query.order_by(ReportRecord.updated_at.desc(), ReportRecord.id)
        .offset((page - 1) * page_size).limit(page_size))).all()
    return ReportPage(items=[ReportSummary(**_summary(row)) for row in rows], total=total, page=page, page_size=page_size)


@business_boundary('report', 'read')
async def list_versions(session, actor, report_id):
    actor = await _identity(session, actor)
    record = await _owned(session, actor, report_id)
    rows = (await session.scalars(select(ReportVersion).where(ReportVersion.report_id == record.id)
        .order_by(ReportVersion.version))).all()
    for row in rows:
        await _scope(session, actor, record, row.snapshot)
    return [ReportVersionDTO(version=row.version, snapshot=_public_snapshot(row.snapshot), draft=row.draft,
        edited_by=row.edited_by, created_at=row.created_at) for row in rows]


async def _persist(session, actor, record, draft, *, edited=False):
    draft = report_generator.validate_draft(draft, record.cached_snapshot)
    record.current_version += 1
    session.add(ReportVersion(report_id=record.id, version=record.current_version,
        snapshot=record.cached_snapshot, draft=draft.model_dump(mode="json"), edited_by=actor.user_id if edited else None))
    record.status = "REVIEWING" if edited else "DRAFT_READY"
    record.error_code = record.error_trace_id = record.error_message = None
    await session.flush()


async def _run(session, actor, record):
    from ..graph.report_graph import report_graph
    started_at = datetime.now(timezone.utc)
    result = await report_graph.ainvoke({"actor": actor, "plan": record.plan,
        "snapshot": record.cached_snapshot}, config={"recursion_limit": 5})
    if result.get("snapshot") is not None:
        record.cached_snapshot = result["snapshot"]
    actor = await _identity(session, actor)
    await _scope(session, actor, record)
    await _available(session, actor, record)
    phase = result.get("failed_phase")
    await runtime_trace_service.record_span(session, tenant_id=actor.tenant_id, trace_id=get_trace_id(),
        node_name="report_graph", tool_name="run_registered_report_query", started_at=started_at,
        finished_at=datetime.now(timezone.utc), status="failed" if phase else "success", error_code=phase,
        thread_id=record.thread_id)
    if phase != "QUERY_FAILED":
        settings = get_settings()
        usage = result.get("model_usage", {})
        await runtime_trace_service.record_model_attempts(session, tenant_id=actor.tenant_id, trace_id=get_trace_id(),
            usage=usage, provider=settings.llm_provider, model_name="report-deterministic"
            if settings.llm_provider == "mock" else getattr(settings, f"{settings.llm_provider}_chat_model"))
    if phase:
        record.status, record.error_code = "PAUSED", phase
        record.error_trace_id = get_trace_id()
        record.error_message = "只读查询暂不可用，请重试或缩小统计范围" if phase == "QUERY_FAILED" else "摘要未通过证据校验，请重试"
        return
    await _persist(session, actor, record, result["draft"])


@business_boundary('report', 'write')
async def approve_plan(session, actor, report_id, payload):
    actor = await _identity(session, actor)
    record = await _owned(session, actor, report_id, lock=True)
    command, fresh = await _claim(session, actor, report_id, "approve", payload)
    if not fresh:
        return await _replay(session, actor, record, command)
    await _available(session, actor, record)
    _expect(record, payload)
    if record.status != "PLAN_READY" or not payload.plan_confirmed:
        raise AppException(ErrorCode.INVALID_STATE, "请先确认已保存的指标、时间和统计范围", http_status=422)
    record.plan_confirmation = {"version": record.current_version, "actor_id": actor.user_id,
        "plan_hash": idempotency_service.payload_digest(record.plan), "scope_fingerprint": record.scope_fingerprint,
        "confirmed_at": datetime.now(timezone.utc).isoformat()}
    await _run(session, actor, record)
    return await _finish(session, actor, record, command, "plan_approved")


@business_boundary('report', 'write')
async def retry(session, actor, report_id, payload):
    actor = await _identity(session, actor)
    record = await _owned(session, actor, report_id, lock=True)
    command, fresh = await _claim(session, actor, report_id, "retry", payload)
    if not fresh:
        return await _replay(session, actor, record, command)
    await _available(session, actor, record)
    _expect(record, payload)
    if record.status != "PAUSED" or record.plan_confirmation is None:
        raise AppException(ErrorCode.INVALID_STATE, "当前报表不可重试", http_status=422)
    await _run(session, actor, record)
    return await _finish(session, actor, record, command, "retried")


@business_boundary('report', 'write')
async def save_draft(session, actor, report_id, payload):
    actor = await _identity(session, actor)
    record = await _owned(session, actor, report_id, lock=True)
    command, fresh = await _claim(session, actor, report_id, "edit", payload)
    if not fresh:
        return await _replay(session, actor, record, command)
    await _available(session, actor, record)
    _expect(record, payload)
    if record.status not in {"DRAFT_READY", "REVIEWING"}:
        raise AppException(ErrorCode.INVALID_STATE, "当前报表不可编辑", http_status=422)
    try:
        draft = report_generator.validate_draft(payload.draft, record.cached_snapshot)
    except ValueError:
        raise AppException(ErrorCode.BAD_REQUEST, "摘要仅支持定性描述，数值请以统计表为准；请核对引用指标", http_status=422) from None
    await _persist(session, actor, record, draft, edited=True)
    return await _finish(session, actor, record, command, "edited")


@business_boundary('report', 'write')
async def publish(session, actor, report_id, payload):
    actor = await _identity(session, actor)
    record = await _owned(session, actor, report_id, lock=True)
    command, fresh = await _claim(session, actor, report_id, "publish", payload)
    if not fresh:
        return await _replay(session, actor, record, command)
    await _available(session, actor, record)
    _expect(record, payload)
    if record.status not in {"DRAFT_READY", "REVIEWING"} or not payload.definitions_confirmed or not payload.causes_acknowledged:
        raise AppException(ErrorCode.INVALID_STATE, "请确认统计口径与原因候选后发布已保存版本", http_status=422)
    record.publication = {"version": record.current_version, "actor_id": actor.user_id,
        "published_at": datetime.now(timezone.utc).isoformat(), "snapshot_hash": idempotency_service.payload_digest(record.cached_snapshot),
        "definitions_confirmed": True, "causes_acknowledged": True, "external_writes": False}
    record.status = "PUBLISHED"
    return await _finish(session, actor, record, command, "published")
