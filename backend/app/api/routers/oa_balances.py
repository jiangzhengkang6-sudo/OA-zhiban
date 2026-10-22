from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.oa_leave import BalanceAdjustment
from ...services import oa_balance_service as service

router=APIRouter(prefix='/oa/balances',tags=['请假额度'])


@router.get('')
async def list_balances(user_id: str|None=None,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await service.list_balances(db,actor,user_id))


@router.post('/adjust')
async def adjust(payload: BalanceAdjustment,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await service.adjust(db,actor,payload)
    await db.commit()
    return ok(result.response())
