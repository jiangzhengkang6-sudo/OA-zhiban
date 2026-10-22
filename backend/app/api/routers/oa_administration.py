from fastapi import APIRouter,Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.oa_workflow import SeatHandoffCommand,RouteResumeCommand
from ...services import oa_handoff_service as handoff,oa_workflow_scheduler as scheduler

router=APIRouter(prefix='/oa/administration',tags=['人工流程管理'])


@router.get('/instances')
async def instances(db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await handoff.list_instances(db,actor))


@router.get('/seats/{seat_id}/candidates')
async def candidates(seat_id: str,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await handoff.candidates(db,actor,seat_id))


@router.post('/seats/{seat_id}/transfer')
async def transfer(seat_id: str,payload: SeatHandoffCommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await handoff.transfer(db,actor,seat_id,payload)
    await db.commit()
    return ok(result.response())


@router.post('/instances/{instance_id}/resume')
async def resume(instance_id: str,payload: RouteResumeCommand,db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    result=await handoff.resume(db,actor,instance_id,payload)
    await db.commit()
    return ok(result.response())


@router.get('/reconciliation')
async def reconciliation(db: AsyncSession=Depends(get_db),actor=Depends(get_current_user)):
    return ok(await scheduler.reconcile(db,actor))
