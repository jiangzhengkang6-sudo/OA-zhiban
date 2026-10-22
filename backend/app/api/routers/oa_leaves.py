from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile, Response
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.oa_leave import LeaveDraftCreate, LeaveDraftPatch, SubmitLeaveCommand, OACommand
from ...services import oa_leave_service as service, oa_attachment_service as attachments

router = APIRouter(prefix='/oa/leaves',tags=['人工请假'])


@router.get('')
async def list_leaves(db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.list_leaves(db,actor))


@router.post('')
async def create(payload: LeaveDraftCreate,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.create_draft(db,actor,payload)
    await db.commit()
    return ok(result.response())


@router.get('/{leave_id}')
async def detail(leave_id: str,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.detail(db,actor,leave_id))


@router.put('/{leave_id}')
async def update(leave_id: str,payload: LeaveDraftPatch,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.update_draft(db,actor,leave_id,payload)
    await db.commit()
    return ok(result.response())


@router.post('/{leave_id}/submit')
async def submit(leave_id: str,payload: SubmitLeaveCommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.submit(db,actor,leave_id,payload)
    await db.commit()
    return ok(result.response())


@router.post('/{leave_id}/attachments')
async def upload(leave_id: str,file: UploadFile=File(...),operation_id: str=Form(...,min_length=1,max_length=64),
                 expected_revision: int=Form(...,ge=1),db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await attachments.upload(db,actor,leave_id,file,operation_id=operation_id,expected_revision=expected_revision)
    await db.commit()
    return ok(result.response())


@router.post('/{leave_id}/withdraw')
async def withdraw(leave_id: str,payload: OACommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.withdraw(db,actor,leave_id,payload)
    await db.commit()
    return ok(result.response())


@router.post('/{leave_id}/archive')
async def archive(leave_id: str,payload: OACommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.archive(db,actor,leave_id,payload)
    await db.commit()
    return ok(result.response())


@router.post('/{leave_id}/attachments/{attachment_id}/scan')
async def rescan(leave_id: str,attachment_id: str,payload: OACommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await attachments.rescan(db,actor,leave_id,attachment_id,operation_id=payload.operation_id,expected_revision=payload.expected_revision)
    await db.commit()
    return ok(result.response())


@router.get('/{leave_id}/attachments/{attachment_id}/content')
async def content(leave_id: str,attachment_id: str,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    row,data=await attachments.download(db,actor,leave_id,attachment_id)
    return Response(data,media_type=row.mime_type,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(row.filename,safe=''),
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
