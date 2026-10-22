"""Document workbench API."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.document import DocumentInput, DocumentCommand, DocumentDraftUpdate, DocumentDecision
from ...services import document_service as service
from ...services.document_templates import TEMPLATES
from ..deps import get_current_user

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/templates")
async def templates(session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    await service._identity(session, user)
    return ok(list(TEMPLATES.values()))


@router.post("")
async def create(payload: DocumentInput, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.create_document(session, user, payload)
    await session.commit()
    return ok(result)


@router.get("")
async def listing(page: int = 1, page_size: int = 20, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.list_documents(session, user, page=page, page_size=page_size))


@router.get("/{document_id}")
async def detail(document_id: str, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.get_document(session, user, document_id))


@router.get("/{document_id}/versions")
async def versions(document_id: str, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.list_versions(session, user, document_id))


@router.post("/{document_id}/generate")
async def generate(document_id: str, payload: DocumentCommand, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.generate_draft(session, user, document_id, payload)
    await session.commit()
    return ok(result)


@router.post("/{document_id}/retry")
async def retry(document_id: str, payload: DocumentCommand, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.generate_draft(session, user, document_id, payload, retry=True)
    await session.commit()
    return ok(result)


@router.patch("/{document_id}/draft")
async def edit(document_id: str, payload: DocumentDraftUpdate, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.save_draft(session, user, document_id, payload)
    await session.commit()
    return ok(result)


@router.post("/{document_id}/decisions")
async def decide(document_id: str, payload: DocumentDecision, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.decide(session, user, document_id, payload)
    await session.commit()
    return ok(result)
