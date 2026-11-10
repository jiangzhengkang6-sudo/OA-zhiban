"""统一 OA 智能助手 V2 路由。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...schemas.assistant_v2 import (
    DraftParseRequest,
    KnowledgeSearchRequest,
    OverviewRequest,
    ReportDraftRequest,
)
from ...schemas.common import ok
from ...services import assistant_v2_service
from ..deps import get_current_user

router = APIRouter(prefix="/assistant-v2", tags=["统一智能助手"])


@router.post("/overview")
async def overview(
    payload: OverviewRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return ok(await assistant_v2_service.overview(session, user, payload))


@router.post("/knowledge/search")
async def knowledge_search(
    payload: KnowledgeSearchRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return ok(await assistant_v2_service.search_knowledge(session, user, payload))


@router.post("/reports/draft")
async def report_draft(
    payload: ReportDraftRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return ok(await assistant_v2_service.create_report_draft(session, user, payload))


@router.post("/drafts/parse")
async def parse_draft(
    payload: DraftParseRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return ok(await assistant_v2_service.parse_natural_draft(session, user, payload))

