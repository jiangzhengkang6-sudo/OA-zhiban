from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..deps import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.oa_workflow import WorkflowSave, PublishWorkflow
from ...services import oa_workflow_service as service

router = APIRouter(prefix='/oa/workflows', tags=['人工流程配置'])


@router.get('')
async def list_workflows(available: bool = False, scene: str | None = None, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.list_definitions(db, actor, available=available,scene=scene))


@router.get('/options')
async def options(resource: str = 'workflow', action: str = 'read', db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    return ok(await service.workbench_options(db, actor, resource=resource, action=action))


@router.post('')
async def create_workflow(payload: WorkflowSave, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.save_definition(db, actor, payload)
    await db.commit()
    return ok(result)


@router.put('/{definition_id}')
async def update_workflow(definition_id: str, payload: WorkflowSave, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.save_definition(db, actor, payload, definition_id)
    await db.commit()
    return ok(result)


@router.post('/{definition_id}/publish')
async def publish_workflow(definition_id: str, payload: PublishWorkflow, db: AsyncSession = Depends(get_db), actor=Depends(get_current_user)):
    result = await service.publish_definition(db, actor, definition_id, payload)
    await db.commit()
    return ok(result.response())
