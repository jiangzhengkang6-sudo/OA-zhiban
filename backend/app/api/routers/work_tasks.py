"""Independent business task API; static paths precede public task IDs."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.work_task import (WorkTaskSourceInput, WorkTaskCommandBase, WorkTaskDraftUpdate,
    WorkTaskDecision, WorkTaskCommand, WorkTaskUpdate)
from ...services import work_task_service as service
from ..deps import get_current_user

router = APIRouter(prefix="/work-tasks", tags=["work-tasks"])


@router.post("/batches")
async def create_batch(payload: WorkTaskSourceInput, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.create_batch(session, user, payload)
    await session.commit()
    return ok(result)


@router.get("/batches")
async def batches(session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.list_batches(session, user))


@router.get("/batches/{batch_id}")
async def batch_detail(batch_id: str, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.get_batch(session, user, batch_id))


@router.get("/batches/{batch_id}/versions")
async def batch_versions(batch_id: str, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.versions(session, user, batch_id))


@router.post("/batches/{batch_id}/extract")
async def extract(batch_id: str, payload: WorkTaskCommandBase, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.extract(session, user, batch_id, payload)
    await session.commit()
    return ok(result)


@router.patch("/batches/{batch_id}/draft")
async def draft(batch_id: str, payload: WorkTaskDraftUpdate, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.save_draft(session, user, batch_id, payload)
    await session.commit()
    return ok(result)


@router.post("/batches/{batch_id}/decisions")
async def decide(batch_id: str, payload: WorkTaskDecision, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.decide(session, user, batch_id, payload)
    await session.commit()
    return ok(result)


@router.get("/notifications")
async def notifications(session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.notifications(session, user))


@router.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: str, payload: WorkTaskCommandBase, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.read_notification(session, user, notification_id, payload)
    await session.commit()
    return ok(result)


@router.get("")
async def tasks(page: int = 1, page_size: int = 20, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.list_tasks(session, user, page, page_size))


@router.get("/{task_id}")
async def detail(task_id: str, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.get_task(session, user, task_id))


@router.get("/{task_id}/events")
async def events(task_id: str, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return ok(await service.events(session, user, task_id))


@router.patch("/{task_id}")
async def update(task_id: str, payload: WorkTaskUpdate, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.update_task(session, user, task_id, payload)
    await session.commit()
    return ok(result)


@router.post("/{task_id}/commands")
async def command(task_id: str, payload: WorkTaskCommand, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await service.task_command(session, user, task_id, payload)
    await session.commit()
    return ok(result)
