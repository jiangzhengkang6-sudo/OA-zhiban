"""Authenticated controls and independently signed Tencent callbacks."""
from typing import Literal
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.oa_meeting import MeetingCommand, MeetingTranscriptionStart
from ...services import meeting_transcription_service as service
from ...providers.meeting_transcription import verify_callback
from ...services.oa_access_service import invalid
from ..deps import get_current_user

router=APIRouter(prefix='/meeting-transcriptions',tags=['会议转写'])


@router.post('/callback/trtc')
async def callback(request: Request, db: AsyncSession=Depends(get_db)):
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>262144: raise invalid('转写回调超过大小限制')
    app_id=request.headers.get('SdkAppId','')
    event=verify_callback(bytes(raw),request.headers.get('Sign',''),app_id)
    await service.receive(db,event,app_id)
    await db.commit()
    return {'code':0}


@router.get('/{meeting_id}')
async def status(meeting_id:str,response:Response,db:AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    response.headers['Cache-Control']='no-store, private'
    return ok(await service.status(db,actor,meeting_id))


@router.post('/{meeting_id}/start')
async def start(meeting_id:str,payload:MeetingTranscriptionStart,db:AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.command(db,actor,meeting_id,payload,'start')
    await db.commit()
    return ok(result.response())


@router.post('/{meeting_id}/{action}')
async def command(meeting_id:str,action:Literal['stop','retry'],payload:MeetingCommand,
                  db:AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.command(db,actor,meeting_id,payload,action)
    await db.commit()
    return ok(result.response())
