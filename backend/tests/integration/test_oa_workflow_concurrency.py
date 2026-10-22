import asyncio
import pytest
from sqlalchemy import select, func
from app.core.errors import AppException
from app.models.oa_leave import OALeaveBalance
from app.models.oa_workflow import OAWorkflowInstance
from app.schemas.oa_leave import BalanceAdjustment, LeaveDraftCreate, SubmitLeaveCommand
from tests.oa_support import oa_db
from tests.api.test_oa_leave_lifecycle import setup_leave, fields


@pytest.mark.parametrize('scenario',['same_key','quota','different_types'])
async def test_independent_sessions_submit_races(oa_db,scenario):
    from app.services import oa_leave_service as leaves, oa_balance_service as balances
    async with oa_db() as db:
        admin,actor,workflow = await setup_leave(db)
        for kind in ['annual','sick']:
            await balances.adjust(db,admin,BalanceAdjustment(operation_id=kind,expected_revision=0,user_id=actor.user_id,
                leave_type=kind,year=2026,total=3,reason='测试'))
        await db.commit()
        first = await leaves.create_draft(db,actor,LeaveDraftCreate(operation_id='first',workflow_definition_id=workflow,fields=fields('2026-10-20','2026-10-21')))
        await db.commit()
        if scenario!='same_key':
            second = await leaves.create_draft(db,actor,LeaveDraftCreate(operation_id='second',workflow_definition_id=workflow,
                fields=fields('2026-10-21' if scenario=='different_types' else '2026-10-23','2026-10-22' if scenario=='different_types' else '2026-10-24',leave_type='sick' if scenario=='different_types' else 'annual')))
            await db.commit()
        else: second=first
    async def submit(item):
        async with oa_db() as db:
            try:
                result = await leaves.submit(db,actor,item.result['id'],SubmitLeaveCommand(operation_id='submit',expected_revision=1,requested_submission_version=1))
                await db.commit()
                return result
            except AppException:
                await db.rollback()
                return None
    results = await asyncio.gather(submit(first),submit(second))
    assert sum(item is not None for item in results)==(2 if scenario=='same_key' else 1)
    if scenario=='same_key': assert sum(item.replayed for item in results)==1
    async with oa_db() as db:
        assert await db.scalar(select(func.count()).select_from(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id==actor.tenant_id))==1
        assert await db.scalar(select(func.sum(OALeaveBalance.reserved)).where(OALeaveBalance.user_id==actor.user_id))==2
