from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.organization import DepartmentInput, PositionInput, UserCreate, UserUpdate, ResetPassword, RoleInput
from ...services import organization_service as service

router = APIRouter(prefix='/organization', tags=['组织管理'])


@router.get('')
async def overview(db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.overview(db, actor))


@router.post('/departments')
async def create_department(payload: DepartmentInput, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.save_department(db, actor, payload))


@router.put('/departments/{target_id}')
async def update_department(target_id: str, payload: DepartmentInput, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.save_department(db, actor, payload, target_id))


@router.post('/positions')
async def create_position(payload: PositionInput, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.save_position(db, actor, payload))


@router.put('/positions/{target_id}')
async def update_position(target_id: str, payload: PositionInput, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.save_position(db, actor, payload, target_id))


@router.post('/users')
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.create_user(db, actor, payload))


@router.put('/users/{target_id}')
async def update_user(target_id: str, payload: UserUpdate, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.update_user(db, actor, target_id, payload))


@router.post('/users/{target_id}/reset-password')
async def reset_password(target_id: str, payload: ResetPassword, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    await service.reset_password(db, actor, target_id, payload)
    return ok()


@router.post('/roles')
async def create_role(payload: RoleInput, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.save_role(db, actor, payload))


@router.put('/roles/{target_id}')
async def update_role(target_id: str, payload: RoleInput, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.save_role(db, actor, payload, target_id))
