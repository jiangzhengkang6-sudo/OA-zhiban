from typing import Literal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...services import oa_work_item_service as service

router = APIRouter(prefix='/oa/work-items', tags=['统一待办'])


@router.get('')
async def pending(source: Literal['approval', 'work_task'] | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.pending(db, actor, source=source, page=page, page_size=page_size))
