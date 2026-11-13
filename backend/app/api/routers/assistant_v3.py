"""统一智能助手 V3 路由。"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...schemas.assistant_v3 import AssistantV3ChatRequest
from ...schemas.common import ok
from ...services import assistant_v3_service
from ..deps import get_current_user

router = APIRouter(prefix="/assistant-v3", tags=["统一智能助手 V3"])


@router.post("/chat")
async def chat(
    payload: AssistantV3ChatRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return ok(await assistant_v3_service.chat(session, user, payload))

