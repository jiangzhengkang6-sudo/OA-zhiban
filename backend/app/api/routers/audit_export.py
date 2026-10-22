"""Controlled audit export endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.enums import AuditAction
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.operations import AuditExportOut, AuditExportRequest
from ...services import audit_export_service, audit_service
from ...models.audit_export import AuditExport
from ..deps import require_audit_access

router = APIRouter(prefix="/audit/exports", tags=["audit"])


def _to_out(export: AuditExport, request) -> AuditExportOut:
    return AuditExportOut(
        id=export.id, requested_by=export.requested_by, status=export.status,
        filters={key: value for key, value in export.filters.items() if not key.startswith('_')},
        row_count=export.row_count, created_at=export.created_at,
        expires_at=export.expires_at, download_url=f"/api/audit/exports/{export.id}/download",
    )


@router.post("")
async def create_export(payload: AuditExportRequest, session: AsyncSession = Depends(get_db), user=Depends(require_audit_access)):
    filters = payload.model_dump(exclude_none=True)
    export = await audit_export_service.create_export(session, requested_by=user.user_id, filters=filters,
                                                      meeting_tenant_id=user.tenant_id)
    await audit_service.audit(session, "audit_export_created", actor_id=user.user_id, target_type="audit_export", target_id=str(export.id), input_summary={"filters": export.filters}, output_summary={"row_count": export.row_count})
    await session.commit()
    return ok(_to_out(export, None).model_dump())


@router.get("/{export_id}")
async def get_export(export_id: UUID, session: AsyncSession = Depends(get_db), user=Depends(require_audit_access)):
    export = await session.get(AuditExport, export_id)
    if export is None:
        from ...core.errors import not_found
        raise not_found("导出记录不存在")
    await audit_export_service.authorize_export(session, export, user)
    return ok(_to_out(export, None).model_dump())


@router.get("/{export_id}/download")
async def download_export(export_id: UUID, session: AsyncSession = Depends(get_db), user=Depends(require_audit_access)):
    export = await session.get(AuditExport, export_id)
    if export is None:
        from ...core.errors import not_found
        raise not_found("导出记录不存在")
    await audit_export_service.authorize_export(session, export, user)
    return FileResponse(audit_export_service.download_path(export), media_type="application/json", filename=f"audit-export-{export.id}.json")


