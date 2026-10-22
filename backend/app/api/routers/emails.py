"""Local mail analysis workbench API."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.email import EmailInput, EmailCommand, EmailDraftUpdate, EmailDecision
from ...services import email_service as service
from ..deps import get_current_user

router = APIRouter(prefix="/emails", tags=["emails"])


@router.post("")
async def create(payload: EmailInput, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.create_email(session, user, payload)
    await session.commit()
    return ok(result)


@router.get("")
async def listing(page: int = 1, page_size: int = 20, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.list_emails(session, user, page=page, page_size=page_size))


@router.get("/{email_id}")
async def detail(email_id: str, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.get_email(session, user, email_id))


@router.get("/{email_id}/versions")
async def versions(email_id: str, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.list_versions(session, user, email_id))


@router.post("/{email_id}/analyze")
async def analyze(email_id: str, payload: EmailCommand, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.analyze(session, user, email_id, payload)
    await session.commit()
    return ok(result)


@router.post("/{email_id}/retry")
async def retry(email_id: str, payload: EmailCommand, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.analyze(session, user, email_id, payload, retry=True)
    await session.commit()
    return ok(result)


@router.patch("/{email_id}/draft")
async def edit(email_id: str, payload: EmailDraftUpdate, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.save_draft(session, user, email_id, payload)
    await session.commit()
    return ok(result)


@router.post("/{email_id}/decisions")
async def decide(email_id: str, payload: EmailDecision, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.decide(session, user, email_id, payload)
    await session.commit()
    return ok(result)
