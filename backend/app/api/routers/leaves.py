"""Built-in leave application APIs."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, UploadFile, File, Response
from urllib.parse import quote
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.leave_application import LeaveApplicationCreate, LeaveApplicationPatch
from ...schemas.interrupt import ResumeRequest
from ...services import leave_application_service
from ...services import leave_attachment_service
from ..deps import get_current_user

router = APIRouter(prefix="/leaves", tags=["leaves"])


@router.post('/{application_id}/attachments')
async def upload_attachment(application_id: UUID, file: UploadFile = File(...),
                            session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await leave_attachment_service.upload(session, user, application_id, file)
    await session.commit()
    return ok(result)


@router.get('/{application_id}/attachments')
async def list_attachments(application_id: UUID, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await leave_attachment_service.list_attachments(session, user, application_id))


@router.post('/{application_id}/attachments/{attachment_id}/scan')
async def scan_attachment(application_id: UUID, attachment_id: UUID,
                          session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await leave_attachment_service.rescan(session, user, application_id, attachment_id)
    await session.commit()
    return ok(result)


@router.get('/{application_id}/attachments/{attachment_id}/content')
async def download_attachment(application_id: UUID, attachment_id: UUID,
                              session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row, content = await leave_attachment_service.download(session, user, application_id, attachment_id)
    await session.commit()
    return Response(content=content, media_type=row.content_type, headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + quote(row.filename, safe=''),
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get("")
async def list_leaves(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                      status: str | None = None, session: AsyncSession = Depends(get_db),
                      user=Depends(get_current_user)):
    return ok(await leave_application_service.list_applications(
        session, user, page=page, page_size=page_size, status=status))


@router.post("")
async def create_leave(payload: LeaveApplicationCreate, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await leave_application_service.create_draft(session, user, payload)
    await session.commit()
    return ok(result)


@router.get("/{application_id}")
async def get_leave(application_id: UUID, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await leave_application_service.get_application(session, user, application_id))


@router.patch("/{application_id}")
async def patch_leave(application_id: UUID, payload: LeaveApplicationPatch,
                      session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await leave_application_service.patch_draft(session, user, application_id, payload)
    await session.commit()
    return ok(result)


@router.post("/{application_id}/submit")
async def submit_leave(application_id: UUID, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await leave_application_service.submit(session, user, application_id)
    await session.commit()
    return ok(result)


@router.get("/{application_id}/versions")
async def list_leave_versions(application_id: UUID, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await leave_application_service.list_versions(session, user, application_id))


@router.post("/{application_id}/decision")
async def decide_leave(application_id: UUID, payload: ResumeRequest,
                       session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await leave_application_service.decide(
        session, user, application_id, payload.action, payload.comment or "",
        payload.edited_data, payload.idempotency_key or f"builtin:{application_id}:{payload.action}"
    )
    await session.commit()
    return ok(result)
