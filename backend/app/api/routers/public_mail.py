"""Public mailbox routes are separate from private analysis records."""
from typing import Literal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.public_mail import MailDraft, MailAction, MailMembers
from ...services import public_mail_service as service
from ..deps import get_current_user

router = APIRouter(prefix='/public-mail', tags=['public-mail'])


@router.get('/status')
async def status(db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.status(db, actor))


@router.post('/setup')
async def setup(db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.setup(db, actor)
    await db.commit()
    return ok(result)


@router.get('/members')
async def members(db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.member_options(db, actor))


@router.put('/members')
async def save_members(payload: MailMembers, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.save_members(db, actor, payload)
    await db.commit()
    return ok(result)


@router.post('/sync')
async def sync(db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.sync(db, actor)
    await db.commit()
    return ok(result)


@router.get('/messages')
async def listing(folder: Literal['inbox', 'pending', 'drafts', 'sent'] = 'inbox',
        search: str = Query(default='', max_length=200), page: int = Query(default=1, ge=1, le=10000),
        db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.listing(db, actor, folder, search, page))


@router.post('/messages')
async def create(payload: MailDraft, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.save_draft(db, actor, payload)
    await db.commit()
    return ok(result)


@router.get('/messages/{message_id}')
async def detail(message_id: str, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.detail(db, actor, message_id)
    await db.commit()
    return ok(result)


@router.patch('/messages/{message_id}')
async def update(message_id: str, payload: MailDraft, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.save_draft(db, actor, payload, message_id)
    await db.commit()
    return ok(result)


@router.post('/messages/{message_id}/actions')
async def action(message_id: str, payload: MailAction, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.action(db, actor, message_id, payload)
    await db.commit()
    return ok(result)


@router.post('/messages/{message_id}/import')
async def import_analysis(message_id: str, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.import_analysis(db, actor, message_id)
    await db.commit()
    return ok(result)


@router.post('/messages/{message_id}/task')
async def convert_task(message_id: str, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.convert_task(db, actor, message_id)
    await db.commit()
    return ok(result)
