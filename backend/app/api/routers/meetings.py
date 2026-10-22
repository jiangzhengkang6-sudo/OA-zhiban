"""Text-only meeting agent API; confirmation never writes to external systems."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.meeting import MeetingCreateRequest, MeetingDecisionRequest, MeetingDraftUpdateRequest, MeetingGenerateRequest
from ...services.meeting_parser import MeetingParseError
from ...services import meeting_service
from ..deps import get_current_user

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.post("")
async def create_meeting(payload: MeetingCreateRequest, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    try:
        result = await meeting_service.create_meeting(session, user, payload)
    except MeetingParseError as exc:
        from ...core.errors import AppException
        from ...core.enums import ErrorCode
        raise AppException(ErrorCode[exc.code], str(exc), http_status=400) from exc
    await session.commit()
    return ok(result)


@router.get("")
async def list_meetings(page: int = 1, page_size: int = 20, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await meeting_service.list_meetings(session, user, page=page, page_size=page_size))


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: str, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await meeting_service.get_meeting(session, user, meeting_id))


@router.post("/{meeting_id}/generate")
async def generate_meeting(meeting_id: str, payload: MeetingGenerateRequest | None = None, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    payload = payload or MeetingGenerateRequest()
    result = await meeting_service.generate_draft(session, user, meeting_id, payload.idempotency_key, payload.expected_version)
    await session.commit()
    return ok(result)


@router.patch("/{meeting_id}/draft")
async def update_meeting_draft(meeting_id: str, payload: MeetingDraftUpdateRequest, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await meeting_service.save_draft(session, user, meeting_id, payload.draft.model_dump(), payload.idempotency_key, payload.expected_version)
    await session.commit()
    return ok(result)


@router.post("/{meeting_id}/decisions")
async def decide_meeting(meeting_id: str, payload: MeetingDecisionRequest, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await meeting_service.decide(session, user, meeting_id, payload.action, payload.reason, payload.idempotency_key, payload.expected_version)
    await session.commit()
    return ok(result)


@router.post("/{meeting_id}/retry")
async def retry_meeting(meeting_id: str, payload: MeetingGenerateRequest | None = None, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    payload = payload or MeetingGenerateRequest()
    result = await meeting_service.generate_draft(session, user, meeting_id, payload.idempotency_key, payload.expected_version, retry=True)
    await session.commit()
    return ok(result)
