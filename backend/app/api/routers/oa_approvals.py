from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter,Depends,Response
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.oa_workflow import DecideNodeCommand
from ...services import oa_approval_service as service

router=APIRouter(prefix='/oa/approvals',tags=['人工审批'])


@router.get('')
async def items(kind: Literal['pending','done','cc']='pending',db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.list_items(db,actor,kind))


@router.get('/nodes/{node_id}')
async def context(node_id: str,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.node_context(db,actor,node_id))


@router.post('/nodes/{node_id}/decisions')
async def decide(node_id: str,payload: DecideNodeCommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    outcome=await service.decide(db,actor,node_id,payload)
    await db.commit()
    return ok(outcome.response())


@router.get('/nodes/{node_id}/attachments/{attachment_id}/content')
async def content(node_id: str,attachment_id: str,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    row,data=await service.download(db,actor,node_id,attachment_id)
    return Response(data,media_type=row.mime_type,headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(row.filename,safe=''),
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
