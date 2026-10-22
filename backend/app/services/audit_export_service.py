"""Create and retrieve controlled, redacted audit exports."""

import json
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.errors import forbidden, AppException, ErrorCode
from ..models.audit_export import AuditExport
from ..repositories import audit_repo
from ..storage.local import LocalObjectStore

_SENSITIVE_KEYS = {
    "authorization", "cookie", "password", "passwd", "secret",
    "token", "access_token", "refresh_token", "api_key", "apikey",
}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "***REDACTED***" if key.lower() in _SENSITIVE_KEYS else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _serialize_event(event) -> dict:
    return {
        "id": event.id,
        "trace_id": event.trace_id,
        "thread_id": str(event.thread_id) if event.thread_id else None,
        "business_id": event.business_id,
        "actor_id": event.actor_id,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "tool_name": event.tool_name,
        "result": event.result,
        "error_code": event.error_code,
        "policy_version": event.policy_version,
        "duration_ms": event.duration_ms,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "input_summary": redact(event.input_summary),
        "output_summary": redact(event.output_summary),
    }


async def create_export(session: AsyncSession, *, requested_by: str, filters: dict, meeting_tenant_id: str | None = None) -> AuditExport:
    if get_settings().oa_provider == "builtin":
        from ..core.context import get_current_user
        from .oa_scope_service import visible_audits
        actor = get_current_user()
        from .authorization_service import require_fresh_identity, require_permission
        actor = await require_fresh_identity(actor, session=session)
        require_permission(actor, 'audit', 'write')
        if actor.tenant_id != meeting_tenant_id or actor.user_id != requested_by:
            raise forbidden('正式审计导出需要当前租户及创建人上下文')
        formal_rows = await visible_audits(session, actor=actor, **{
            key: value for key, value in filters.items() if key in _FORMAL_FILTERS})
        formal_rows = formal_rows[:filters.get('page_size', 1000)]
        payload_rows = []
        for row in formal_rows:
            payload_rows.append({"id": row.id, "actor_id": row.actor_id, "resource": row.resource,
                "action": row.action, "object_type": row.object_type, "object_id": row.object_id,
                "source_type": row.source_type, "source_id": row.source_id, "trace_id": row.trace_id,
                "policy_version": row.policy_version, "result": row.result,
                "created_at": row.created_at.isoformat() if row.created_at else None, "detail": redact(row.detail)})
        now = datetime.now(timezone.utc)
        public_filters = _json_filters(filters)
        payload = json.dumps({'filters': public_filters, 'total': len(payload_rows), 'items': payload_rows},
            ensure_ascii=False, indent=2).encode('utf-8')
        export = AuditExport(requested_by=requested_by, status="completed", filters={**public_filters,
            'meeting_tenant_id': meeting_tenant_id, '_formal_audit': {
                'scope': _scope(actor), 'row_ids': [row.id for row in formal_rows],
                'sha256': sha256(payload).hexdigest()}},
            row_count=len(payload_rows), expires_at=now + timedelta(hours=get_settings().audit_export_retention_hours))
        session.add(export)
        await session.flush()
        export.storage_ref = LocalObjectStore(get_settings().audit_export_storage_dir).put(payload, f'{export.id}.json')
        await session.flush()
        return export
    items, total = await audit_repo.query_events(session, page=1, meeting_tenant_id=meeting_tenant_id, **filters)
    # The existing audit schema stores timestamps without timezone metadata.
    now = datetime.utcnow()
    export = AuditExport(
        requested_by=requested_by,
        status="completed",
        filters=_json_filters(filters),
        row_count=total,
        expires_at=now + timedelta(hours=get_settings().audit_export_retention_hours),
    )
    if meeting_tenant_id is not None:
        export.filters["meeting_tenant_id"] = meeting_tenant_id
    session.add(export)
    await session.flush()
    reference = f"{export.id}.json"
    payload = {"filters": export.filters, "total": total, "items": [_serialize_event(item) for item in items]}
    export.storage_ref = LocalObjectStore(get_settings().audit_export_storage_dir).put(
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), reference
    )
    await session.flush()
    return export


_FORMAL_FILTERS = {'resource', 'trace_id', 'thread_id', 'business_id', 'actor_id', 'action', 'start_time', 'end_time'}


def _json_filters(filters):
    return {key: str(value) if isinstance(value, UUID) else value.isoformat() if isinstance(value, datetime) else value
        for key, value in filters.items() if value is not None}


def _scope(actor):
    return {'departments': sorted(actor.depts), 'audit': sorted(
        [p['action'], p['scope']] for p in actor.data_scope.get('permissions', []) if p['resource'] == 'audit')}


async def authorize_export(session, export, actor):
    filters = export.filters or {}
    if get_settings().oa_provider != 'builtin':
        if filters.get('meeting_tenant_id') not in {None, actor.tenant_id}:
            raise forbidden('无权访问该导出记录')
        return
    from .authorization_service import require_fresh_identity, require_permission
    from .oa_scope_service import visible_audits
    actor = await require_fresh_identity(actor, session=session)
    require_permission(actor, 'audit', 'read')
    metadata = filters.get('_formal_audit') or {}
    scope = _scope(actor)
    if (export.requested_by != actor.user_id or filters.get('meeting_tenant_id') != actor.tenant_id
            or metadata.get('scope') != scope):
        raise forbidden('导出归属或权限范围已变化，请重新导出')
    expiry = export.expires_at
    if expiry is None or expiry.replace(tzinfo=expiry.tzinfo or timezone.utc) <= datetime.now(timezone.utc):
        raise AppException(ErrorCode.INVALID_STATE, '审计导出已过期，请重新导出', http_status=410)
    rows = await visible_audits(session, actor=actor)
    row_ids = metadata.get('row_ids')
    if not isinstance(row_ids, list) or not set(row_ids).issubset({row.id for row in rows}):
        raise forbidden('导出来源权限已变化，请重新导出')
    try:
        content_hash = sha256(download_path(export).read_bytes()).hexdigest()
    except (ValueError, OSError):
        raise forbidden('导出文件已失效，请重新导出') from None
    if content_hash != metadata.get('sha256'):
        raise forbidden('导出文件完整性校验失败，请重新导出')


def download_path(export: AuditExport):
    if not export.storage_ref:
        raise FileNotFoundError(export.id)
    return LocalObjectStore(get_settings().audit_export_storage_dir).path(export.storage_ref)
