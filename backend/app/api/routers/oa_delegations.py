from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.oa_delegation import DelegationCreate, DelegationRevoke
from ...services import oa_delegation_service as service

router = APIRouter(prefix='/oa/delegations', tags=['限时审批委托'])


@router.get('')
async def items(db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.list_items(db, actor))


@router.get('/candidates')
async def candidates(db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.candidates(db, actor))


@router.post('')
async def create(payload: DelegationCreate, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    outcome = await service.create(db, actor, payload)
    await db.commit()
    return ok(outcome.response())


@router.post('/{identifier}/revoke')
async def revoke(identifier: str, payload: DelegationRevoke, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    outcome = await service.revoke(db, actor, identifier, payload)
    await db.commit()
    return ok(outcome.response())
