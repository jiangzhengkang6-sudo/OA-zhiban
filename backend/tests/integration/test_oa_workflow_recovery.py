import asyncio
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select,func,update
from app.core.errors import AppException
from app.models.identity import OAUser,OAMembership
from app.models.oa_leave import OALeave,OALeaveBalance
from app.models.oa_workflow import OAWorkflowNode,OAWorkflowSeat,OAWorkflowInstance,OAWorkflowEvent
from app.schemas.oa_workflow import DecideNodeCommand
from tests.oa_support import oa_db,seed
from tests.api.test_oa_approval_modes import submitted


@pytest.mark.parametrize('valid_manager',[True,False])
async def test_two_schedulers_restart_and_single_escalation(oa_db,valid_manager):
    from app.services import oa_workflow_scheduler as timers,oa_approval_service as approvals
    async with oa_db() as db:
        first,_,replacement,actor,leave_id=await submitted(db)
        node_id=(await approvals.list_items(db,first,'pending'))[0]['node_id']
        node=await db.get(OAWorkflowNode,node_id)
        due=datetime.now(timezone.utc)-timedelta(seconds=1)
        node.due_at=due
        if valid_manager:
            member=await db.get(OAMembership,(actor.tenant_id,first.user_id))
            member.manager_id=replacement.user_id
        await db.commit()
    async def scan():
        async with oa_db() as db:
            result=await timers.scan(db,now=due+timedelta(seconds=2),actor=first)
            await db.commit()
            return result
    await asyncio.gather(scan(),scan())
    await scan()
    async with oa_db() as db:
        instance=await db.get(OAWorkflowInstance,node.instance_id)
        seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node_id))
        assert instance.state==('IN_REVIEW' if valid_manager else 'PAUSED')
        assert seat.effective_user_id==(replacement.user_id if valid_manager else first.user_id)
        assert seat.escalated==valid_manager
        events=(await db.scalars(select(OAWorkflowEvent).where(OAWorkflowEvent.tenant_id==actor.tenant_id,
            OAWorkflowEvent.action.in_(['workflow.escalate','workflow.pause'])))).all()
        assert len(events)==1


async def test_reconciliation_is_read_only_and_bad_ledger_blocks_decision(oa_db):
    from app.services import oa_workflow_scheduler as timers,oa_approval_service as approvals
    async with oa_db() as db:
        first,_,_,actor,leave_id=await submitted(db)
        node=(await approvals.list_items(db,first,'pending'))[0]['node_id']
        balance=await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
        balance.total+=1
        await db.commit()
        report=await timers.reconcile(db,first)
        assert not report['ok'] and report['issues']
        assert (await db.get(OALeave,leave_id,populate_existing=True)).state=='IN_REVIEW'
        assert balance.total==6
        with pytest.raises(AppException):
            await approvals.decide(db,first,node,DecideNodeCommand(operation_id='badledger',expected_revision=1,action='approve'))
        await db.rollback()
        await timers.scan(db,actor=first)
        await db.commit()
        assert (await db.get(OALeave,leave_id,populate_existing=True)).state=='PAUSED'
        assert (await db.get(OALeaveBalance,balance.id,populate_existing=True)).total==6


async def test_scheduler_requires_current_management_authority_and_terminal_skip(oa_db):
    from app.services import oa_workflow_scheduler as timers,oa_approval_service as approvals
    async with oa_db() as db:
        first,_,_,actor,leave_id=await submitted(db)
        node=(await approvals.list_items(db,first,'pending'))[0]['node_id']
        with pytest.raises(AppException): await timers.reconcile(db,actor)
        await db.rollback()
        assert (await timers.scan(db,actor=actor))['processed']==0
        await db.rollback()
        await approvals.decide(db,first,node,DecideNodeCommand(operation_id='finish',expected_revision=1,action='approve'))
        await db.commit()
        before=await db.scalar(select(func.count()).select_from(OAWorkflowEvent).where(OAWorkflowEvent.tenant_id==actor.tenant_id))
        await timers.scan(db,actor=first,now=datetime.now(timezone.utc)+timedelta(days=30))
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(OAWorkflowEvent).where(OAWorkflowEvent.tenant_id==actor.tenant_id))==before
