"""Task center list, detail and recovery actions."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...schemas.common import ok
from ...services import task_service
from ..deps import get_current_user

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
async def list_tasks(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                     scene: Optional[str] = None, status: Optional[str] = None,
                     updated_after: Optional[datetime] = None, updated_before: Optional[datetime] = None,
                     inbox: bool = False,
                     session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await task_service.list_tasks(session, user, page=page, page_size=page_size,
                                            scene=scene, status=status,
                                            updated_after=updated_after, updated_before=updated_before, inbox=inbox))


@router.get("/{task_id}")
async def get_task(task_id: UUID, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await task_service.get_task(session, task_id, user))


@router.post("/{task_id}/handoff")
async def handoff_task(task_id: UUID, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await task_service.handoff_task(session, task_id, user))


@router.post("/{task_id}/retry")
async def retry_task(task_id: UUID, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await task_service.retry_task(session, task_id, user))
