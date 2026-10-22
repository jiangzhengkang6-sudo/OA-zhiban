"""Owner-private report workbench routes."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.report import ReportInput, ReportPlanApproval, ReportCommand, ReportDraftUpdate, ReportPublication
from ...services import report_service as service
from ...services.report_metrics import METRICS
from ..deps import get_current_user

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/metrics")
async def metrics(session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    await service._identity(session, user)
    return ok(list(METRICS.values()))


@router.post("")
async def create(payload: ReportInput, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.create_report(session, user, payload)
    await session.commit()
    return ok(result)


@router.get("")
async def listing(page: int = 1, page_size: int = 20, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.list_reports(session, user, page=page, page_size=page_size))


@router.get("/{report_id}")
async def detail(report_id: str, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.get_report(session, user, report_id))


@router.get("/{report_id}/versions")
async def versions(report_id: str, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.list_versions(session, user, report_id))


@router.post("/{report_id}/approve-plan")
async def approve(report_id: str, payload: ReportPlanApproval, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.approve_plan(session, user, report_id, payload)
    await session.commit()
    return ok(result)


@router.post("/{report_id}/retry")
async def retry(report_id: str, payload: ReportCommand, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.retry(session, user, report_id, payload)
    await session.commit()
    return ok(result)


@router.patch("/{report_id}/draft")
async def edit(report_id: str, payload: ReportDraftUpdate, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.save_draft(session, user, report_id, payload)
    await session.commit()
    return ok(result)


@router.post("/{report_id}/publish")
async def publish(report_id: str, payload: ReportPublication, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.publish(session, user, report_id, payload)
    await session.commit()
    return ok(result)
