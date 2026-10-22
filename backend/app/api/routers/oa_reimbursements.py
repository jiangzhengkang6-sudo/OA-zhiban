from urllib.parse import quote

from fastapi import APIRouter,Depends,File,Form,UploadFile,Response
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.oa_leave import OACommand
from ...schemas.oa_reimbursement import ReimbursementDraftCreate,ReimbursementDraftPatch,SubmitReimbursementCommand
from ...services import oa_reimbursement_service as service,oa_reimbursement_attachment_service as attachments

router=APIRouter(prefix='/oa/reimbursements',tags=['人工报销'])


@router.get('')
async def list_items(db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.list_reimbursements(db,actor))


@router.post('')
async def create(payload: ReimbursementDraftCreate,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.create_draft(db,actor,payload)
    await db.commit()
    return ok(result.response())


@router.get('/{reimbursement_id}')
async def detail(reimbursement_id: str,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.detail(db,actor,reimbursement_id))


@router.put('/{reimbursement_id}')
async def update(reimbursement_id: str,payload: ReimbursementDraftPatch,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.update_draft(db,actor,reimbursement_id,payload)
    await db.commit()
    return ok(result.response())


@router.post('/{reimbursement_id}/submit')
async def submit(reimbursement_id: str,payload: SubmitReimbursementCommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.submit(db,actor,reimbursement_id,payload)
    await db.commit()
    return ok(result.response())


@router.post('/{reimbursement_id}/withdraw')
async def withdraw(reimbursement_id: str,payload: OACommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.withdraw(db,actor,reimbursement_id,payload)
    await db.commit()
    return ok(result.response())


@router.post('/{reimbursement_id}/archive')
async def archive(reimbursement_id: str,payload: OACommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.archive(db,actor,reimbursement_id,payload)
    await db.commit()
    return ok(result.response())


@router.post('/{reimbursement_id}/attachments')
async def upload(reimbursement_id: str,file: UploadFile=File(...),operation_id: str=Form(...,min_length=1,max_length=64),
                 expected_revision: int=Form(...,ge=1),db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await attachments.upload(db,actor,reimbursement_id,file,operation_id=operation_id,expected_revision=expected_revision)
    await db.commit()
    return ok(result.response())


@router.post('/{reimbursement_id}/attachments/{attachment_id}/scan')
async def rescan(reimbursement_id: str,attachment_id: str,payload: OACommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await attachments.rescan(db,actor,reimbursement_id,attachment_id,operation_id=payload.operation_id,expected_revision=payload.expected_revision)
    await db.commit()
    return ok(result.response())


@router.get('/{reimbursement_id}/attachments/{attachment_id}/content')
async def content(reimbursement_id: str,attachment_id: str,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    row,data=await attachments.download(db,actor,reimbursement_id,attachment_id)
    return Response(data,media_type=row.mime_type,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(row.filename,safe=''),
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
