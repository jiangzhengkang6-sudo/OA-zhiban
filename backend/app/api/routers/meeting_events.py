from typing import Literal
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.oa_meeting import MeetingCreate, MeetingUpdate, MeetingFields, MeetingCommand, MeetingReply, MeetingMinutes
from ...services import meeting_management_service as service
from ..deps import get_current_user

router = APIRouter(prefix='/meeting-events', tags=['会议管理'])


@router.get('/options')
async def options(db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.options(db, actor))


@router.post('/conflicts')
async def conflicts(payload: MeetingFields, exclude_id: str | None = None,
                    db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.conflicts(db, actor, payload, exclude_id))


@router.get('')
async def items(mode: Literal['all','organized','invited'] = 'all',
                db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.list_items(db, actor, mode))


@router.post('')
async def create(payload: MeetingCreate, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.save(db, actor, payload)
    await db.commit()
    return ok(result.response())


@router.get('/{meeting_id}')
async def detail(meeting_id: str, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.detail(db, actor, meeting_id))


@router.put('/{meeting_id}')
async def update(meeting_id: str, payload: MeetingUpdate, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.save(db, actor, payload, meeting_id)
    await db.commit()
    return ok(result.response())


@router.post('/{meeting_id}/reply')
async def reply(meeting_id: str, payload: MeetingReply, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.reply(db, actor, meeting_id, payload)
    await db.commit()
    return ok(result.response())


@router.post('/{meeting_id}/minutes')
async def minutes(meeting_id: str, payload: MeetingMinutes, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.attach_minutes(db, actor, meeting_id, payload)
    await db.commit()
    return ok(result.response())


@router.post('/{meeting_id}/retry-notifications')
async def retry(meeting_id: str, payload: MeetingCommand, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.retry_notifications(db, actor, meeting_id, payload)
    await db.commit()
    return ok(result.response())


@router.post('/{meeting_id}/video-session')
async def video_session(meeting_id: str, response: Response,
                        db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    from ...services.meeting_video_service import admission
    response.headers['Cache-Control'] = 'no-store, private'
    response.headers['Pragma'] = 'no-cache'
    result = await admission(db, actor, meeting_id)
    await db.commit()
    return ok(result)


@router.post('/{meeting_id}/{action}')
async def transition(meeting_id: str, action: Literal['publish','start','end','cancel'], payload: MeetingCommand,
                     db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.transition(db, actor, meeting_id, payload, action)
    await db.commit()
    return ok(result.response())
