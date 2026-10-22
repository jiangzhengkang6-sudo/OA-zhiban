"""客服人工队列与处理回写接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.support import (
    SupportQueueAssignment,
    SupportQueueCompletion,
    SupportQueueItemResponse,
    SupportQueueListResponse,
)
from ...services import support_queue_service
from ..deps import require_roles

router = APIRouter(prefix="/support", tags=["support"])


@router.get("/queue")
async def get_support_queue(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("cs")),
):
    result = await support_queue_service.list_queue(
        session, user, status=status, page=page, page_size=page_size,
    )
    return ok(SupportQueueListResponse(**result))


@router.get("/queue/{item_id}")
async def get_support_queue_item(
    item_id: UUID,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("cs")),
):
    result = await support_queue_service.get_item(session, user, item_id)
    return ok(SupportQueueItemResponse(**result))


@router.post("/queue/{item_id}/accept")
async def accept_support_queue_item(
    item_id: UUID,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("cs")),
):
    result = await support_queue_service.accept(session, user, item_id)
    await session.commit()
    return ok(SupportQueueItemResponse(**result))


@router.post("/queue/{item_id}/assign")
async def assign_support_queue_item(
    item_id: UUID,
    payload: SupportQueueAssignment,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("cs")),
):
    result = await support_queue_service.assign(session, user, item_id, payload.assignee_id)
    await session.commit()
    return ok(SupportQueueItemResponse(**result))


@router.post("/queue/{item_id}/complete")
async def complete_support_queue_item(
    item_id: UUID,
    payload: SupportQueueCompletion,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("cs")),
):
    result = await support_queue_service.complete(
        session, user, item_id, payload.resolution, payload.status,
    )
    await session.commit()
    return ok(SupportQueueItemResponse(**result))
