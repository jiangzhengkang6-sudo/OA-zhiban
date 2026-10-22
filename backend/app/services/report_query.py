"""Registry-only SELECTs in a separate PostgreSQL read-only transaction."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text

from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..db.session import async_session_factory
from ..models.agent_thread import AgentThread
from ..models.approval_instance import ApprovalInstance
from ..models.ticket_record import TicketRecord
from ..models.work_task import WorkTask
from ..models.work_task_batch import WorkTaskBatch
from ..models.oa_ticket import OATicket
from ..models.oa_workflow import OAWorkflowInstance
from ..models.oa_leave import OALeave, OALeaveVersion
from ..models.oa_reimbursement import OAReimbursement, OAReimbursementVersion
from .idempotency_service import payload_digest
from .report_metrics import METRICS, ANOMALY_RULE
from .authorization_service import require_permission, require_fresh_identity, resource_clause
from .oa_access_service import department_permission

MAX_SOURCE_ROWS = 10000


def scope_fingerprint(actor, scope):
    if scope == 'department' and (actor.data_scope.get('identity_provider') != 'builtin'
            or not actor.depts or not department_permission(actor, 'report', 'read')):
        raise AppException(ErrorCode.FORBIDDEN, '部门统计需要当前部门的报表读取权限', http_status=403)
    if scope == 'tenant' and actor.data_scope.get('identity_provider') == 'builtin':
        raise AppException(ErrorCode.FORBIDDEN, '正式业务尚未开放租户全域统计权限，请使用本人范围', http_status=403)
    if scope == "tenant" and not ("admin" in actor.roles and actor.data_scope.get("all") is True):
        raise AppException(ErrorCode.FORBIDDEN, "租户汇总需要当前全域管理员权限", http_status=403)
    return payload_digest({"tenant_id": actor.tenant_id, "user_id": actor.user_id,
        "roles": sorted(actor.roles), "depts": sorted(actor.depts), "data_scope": actor.data_scope, "scope": scope})


def source_query(metric_id, actor, scope):
    if actor.data_scope.get('identity_provider') == 'builtin':
        scope_fingerprint(actor, scope)
        if metric_id == 'ticket_volume':
            require_permission(actor, 'ticket', 'read')
            return OATicket, select(OATicket.id, OATicket.created_at, OATicket.state.label('status')).where(
                OATicket.tenant_id == actor.tenant_id, resource_clause(actor, 'ticket', OATicket.owner_id)
                if scope == 'department' else OATicket.owner_id == actor.user_id)
        if metric_id == 'approval_outcomes':
            return _formal_approval_query(actor, scope)
        if metric_id == 'work_task_progress':
            require_permission(actor, 'work_task', 'read')
            return WorkTask, select(WorkTask.id, WorkTask.created_at, WorkTask.status).where(
                WorkTask.tenant_id == actor.tenant_id,
                or_(WorkTask.creator_id == actor.user_id, WorkTask.assignee_id == actor.user_id))
    if metric_id == "ticket_volume":
        model = TicketRecord
        query = select(model.id, model.created_at, model.status).where(model.tenant_id == actor.tenant_id)
        if scope == "own":
            query = query.where(model.user_id == actor.user_id)
    elif metric_id == "approval_outcomes":
        model = ApprovalInstance
        query = select(model.id, model.created_at, model.status).join(AgentThread, model.thread_id == AgentThread.id).where(
            model.tenant_id == actor.tenant_id, AgentThread.tenant_id == actor.tenant_id)
        if scope == "own":
            query = query.where(AgentThread.user_id == actor.user_id)
    elif metric_id == "work_task_progress":
        model = WorkTask
        query = select(model.id, model.created_at, model.status).where(model.tenant_id == actor.tenant_id)
        if scope == "own":
            query = query.where(or_(model.creator_id == actor.user_id, model.assignee_id == actor.user_id))
    else:
        raise ValueError("unregistered metric")
    return model, query


def _formal_approval_query(actor, scope):
    query = select(OAWorkflowInstance.id, OAWorkflowInstance.created_at, OAWorkflowInstance.state.label('status'))
    scopes = []
    for scene, model, version, association, key in (
        ('leave', OALeave, OALeaveVersion, 'leave_version_id', 'leave_id'),
        ('reimbursement', OAReimbursement, OAReimbursementVersion, 'reimbursement_version_id', 'reimbursement_id')):
        query = query.outerjoin(version, (getattr(OAWorkflowInstance, association) == version.id) &
            (OAWorkflowInstance.tenant_id == version.tenant_id)).outerjoin(model,
            (getattr(version, key) == model.id) & (version.tenant_id == model.tenant_id))
        if any(p['resource'] == scene and p['action'] == 'read' for p in actor.data_scope.get('permissions', [])):
            source_scope = resource_clause(actor, scene, model.applicant_id) if scope == 'department' else model.applicant_id == actor.user_id
            scopes.append((OAWorkflowInstance.scene == scene) & source_scope)
    if not scopes:
        raise AppException(ErrorCode.FORBIDDEN, '当前账号没有审批业务来源读取权限', http_status=403)
    return OAWorkflowInstance, query.where(OAWorkflowInstance.tenant_id == actor.tenant_id, or_(*scopes))


async def _visible_rows(session, actor, model, rows):
    if model is not WorkTask or actor.data_scope.get('identity_provider') != 'builtin':
        return rows
    from .work_task_service import _source_access
    visible = []
    for row in rows:
        batch = await session.scalar(select(WorkTaskBatch).join(WorkTask, WorkTask.batch_id == WorkTaskBatch.id).where(
            WorkTask.id == row.id, WorkTaskBatch.tenant_id == actor.tenant_id))
        if batch is None:
            continue
        try:
            await _source_access(session, actor, batch)
        except AppException as error:
            if error.http_status not in {403, 404, 422}:
                raise
            continue
        visible.append(row)
    return visible


async def validate_snapshot_scope(session, actor, plan, snapshot):
    actor = await require_fresh_identity(actor, session=session)
    require_permission(actor, 'report', 'read')
    scope_fingerprint(actor, plan.scope)
    for metric_id in plan.metrics:
        source_query(metric_id, actor, plan.scope)
    if not snapshot:
        return
    for metric in snapshot["metrics"]:
        model, query = source_query(metric["metric_id"], actor, plan.scope)
        ids = {str(value) if model in {OATicket, OAWorkflowInstance} else UUID(value) for value in metric["source_ids"]}
        if not ids:
            continue
        rows = (await session.execute(query.where(model.id.in_(ids)))).all()
        found = {row.id for row in await _visible_rows(session, actor, model, rows)}
        if found != ids:
            raise AppException(ErrorCode.FORBIDDEN, "报表来源权限已变化，请重新创建并确认计划", http_status=403)


async def execute_plan(actor, plan):
    scope = scope_fingerprint(actor, plan.scope)
    metrics = []
    async with async_session_factory() as session:
        # This transaction only reads and is rolled back, including identity
        # refreshes; AuthorizedSession's write-commit locks must never run here.
        try:
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            await session.execute(text("SET LOCAL statement_timeout = '5s'"))
            actor = await require_fresh_identity(actor, session=session)
            require_permission(actor, 'report', 'read')
            scope = scope_fingerprint(actor, plan.scope)
            for metric_id in plan.metrics:
                model, query = source_query(metric_id, actor, plan.scope)
                rows = (await session.execute(query.where(model.created_at >= plan.previous_start,
                    model.created_at < plan.end).order_by(model.created_at, model.id).limit(MAX_SOURCE_ROWS + 1))).all()
                if len(rows) > MAX_SOURCE_ROWS:
                    raise ValueError("source row budget exceeded; narrow the report range")
                rows = await _visible_rows(session, actor, model, rows)
                current = [row for row in rows if row.created_at >= plan.start]
                previous = len(rows) - len(current)
                daily = Counter(row.created_at.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat() for row in current)
                buckets = []
                cursor = plan.start
                while cursor < plan.end:
                    day = cursor.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
                    buckets.append({"day": day, "value": daily[day]})
                    cursor += timedelta(days=1)
                delta = round((len(current) - previous) * 100 / previous, 2) if previous else None
                metrics.append({**METRICS[metric_id], "source": model.__tablename__, "current": len(current), "previous": previous,
                    "change_percent": delta, "comparison_available": previous > 0,
                    "anomaly_candidate": delta is not None and abs(delta) >= ANOMALY_RULE["threshold_percent"],
                    "status_counts": dict(Counter(row.status for row in current)), "buckets": buckets,
                    "source_ids": [str(row.id) for row in rows]})
        finally:
            await session.rollback()
    return {"version": 1, "plan": plan.model_dump(mode="json"), "scope_fingerprint": scope,
        "queried_at": datetime.now(timezone.utc).isoformat(), "timezone": "Asia/Shanghai",
        "previous_start": plan.previous_start.isoformat(), "previous_end": plan.previous_end.isoformat(),
        "interval": "[start,end)", "anomaly_rule": ANOMALY_RULE, "metrics": metrics,
        "source_row_limit": MAX_SOURCE_ROWS, "read_only": True}
