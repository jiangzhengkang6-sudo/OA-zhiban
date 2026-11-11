"""统一 OA 智能助手 V2 路由。"""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...schemas.assistant_v2 import (
    DraftCancelRequest,
    DraftConfirmRequest,
    DraftSaveRequest,
    DraftParseRequest,
    KnowledgeSearchRequest,
    OverviewRequest,
    ReportDraftRequest,
    ScheduleResumeRequest,
)
from ...schemas.common import ok
from ...services import assistant_v2_service
from ..deps import get_current_user

router = APIRouter(prefix="/assistant-v2", tags=["统一智能助手"])


@router.get("/options")
async def options(
    draft_type: Literal["task", "meeting"],
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return ok(await assistant_v2_service.options(session, user, draft_type))


@router.get("/items")
async def items(
    draft_type: Literal["task", "meeting"],
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return ok(await assistant_v2_service.list_existing_items(session, user, draft_type))


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


@router.post("/drafts")
async def save_draft(
    payload: DraftSaveRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await assistant_v2_service.save_draft(session, user, payload)
    await session.commit()
    return ok(result)


@router.get("/drafts")
async def list_drafts(
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return ok(await assistant_v2_service.list_saved_drafts(session, user))


@router.get("/drafts/{draft_id}")
async def get_draft(
    draft_id: str,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return ok(await assistant_v2_service.get_saved_draft(session, user, draft_id))


@router.post("/drafts/{draft_id}/confirm")
async def confirm_draft(
    draft_id: str,
    payload: DraftConfirmRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await assistant_v2_service.confirm_draft(session, user, draft_id, payload)
    await session.commit()
    return ok(result)


@router.post("/drafts/{draft_id}/cancel")
async def cancel_draft(
    draft_id: str,
    payload: DraftCancelRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await assistant_v2_service.cancel_saved_draft(session, user, draft_id, payload)
    await session.commit()
    return ok(result)


@router.get("/schedules")
async def list_schedules(
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return ok(await assistant_v2_service.list_schedule_rules(session, user))


@router.post("/schedules/{schedule_id}/cancel")
async def cancel_schedule(
    schedule_id: str,
    payload: DraftCancelRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await assistant_v2_service.cancel_schedule_rule(
        session,
        user,
        schedule_id,
        payload.reason,
    )
    await session.commit()
    return ok(result)


@router.post("/schedules/{schedule_id}/resume")
async def resume_schedule(
    schedule_id: str,
    payload: ScheduleResumeRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await assistant_v2_service.resume_schedule_rule(
        session,
        user,
        schedule_id,
        payload.note,
    )
    await session.commit()
    return ok(result)

