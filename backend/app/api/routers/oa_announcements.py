from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.oa_announcement import AnnouncementCreate, AnnouncementUpdate
from ...schemas.oa_leave import OACommand
from ...services import oa_announcement_service as service

router = APIRouter(prefix='/oa/announcements', tags=['部门公告'])


@router.get('')
async def items(manage: bool = False, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.list_items(db, actor, manage=manage))


@router.get('/{announcement_id}')
async def detail(announcement_id: str, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.detail(db, actor, announcement_id))


@router.post('')
async def create(payload: AnnouncementCreate, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.save(db, actor, payload)
    await db.commit()
    return ok(result.response())


@router.put('/{announcement_id}')
async def save(announcement_id: str, payload: AnnouncementUpdate, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.save(db, actor, payload, announcement_id)
    await db.commit()
    return ok(result.response())


@router.post('/{announcement_id}/publish')
async def publish(announcement_id: str, payload: OACommand, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.transition(db, actor, announcement_id, payload, 'publish')
    await db.commit()
    return ok(result.response())


@router.post('/{announcement_id}/withdraw')
async def withdraw(announcement_id: str, payload: OACommand, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.transition(db, actor, announcement_id, payload, 'withdraw')
    await db.commit()
    return ok(result.response())


@router.post('/{announcement_id}/read')
async def read(announcement_id: str, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.mark_read(db, actor, announcement_id)
    await db.commit()
    return ok(result)
