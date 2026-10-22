import asyncio
import pytest
from sqlalchemy import select,func
from app.core.errors import AppException
from app.models.oa_leave import OALeave,OALeaveBalance,OALeaveLedger
from app.models.oa_workflow import OAWorkflowEvent,OAWorkflowOutbox,OAWorkflowNode,OAWorkflowSeat
from app.schemas.oa_leave import OACommand
from app.schemas.oa_workflow import DecideNodeCommand
from tests.oa_support import oa_db
from tests.api.test_oa_approval_modes import submitted


@pytest.mark.parametrize('kind',['any','withdraw','same_key'])
async def test_independent_sessions_terminal_races(oa_db,kind):
    from app.services import oa_approval_service as approvals,oa_leave_service as leaves
    async with oa_db() as db:
        first,second,_,actor,leave_id=await submitted(db,mode='any')
        node=(await approvals.list_items(db,first,'pending'))[0]['node_id']
    async def run(index):
        async with oa_db() as db:
            try:
                if kind=='withdraw' and index==1:
                    result=await leaves.withdraw(db,actor,leave_id,OACommand(operation_id='withdraw',expected_revision=2))
                else:
                    result=await approvals.decide(db,first if index==0 or kind=='same_key' else second,node,
                        DecideNodeCommand(operation_id='race',expected_revision=1,action='approve'))
                await db.commit()
                return result
            except AppException:
                await db.rollback()
                return None
    results=await asyncio.gather(run(0),run(1))
    assert sum(r is not None for r in results)==(2 if kind=='same_key' else 1)
    if kind=='same_key': assert sum(r.replayed for r in results)==1
    async with oa_db() as db:
        leave=await db.get(OALeave,leave_id)
        balance=await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
        assert leave.state in {'APPROVED','CANCELLED'}
        assert (balance.used,balance.reserved)==(int(leave.state=='APPROVED'),0)
        assert await db.scalar(select(func.count()).select_from(OALeaveLedger).where(
            OALeaveLedger.tenant_id==actor.tenant_id,OALeaveLedger.kind.in_(['RELEASE','CONSUME'])))==1


@pytest.mark.parametrize('failure',['event','outbox','ledger'])
async def test_last_approval_failure_restores_all_state(oa_db,monkeypatch,failure):
    from app.services import oa_approval_service as approvals,oa_command_service as commands
    async with oa_db() as db:
        first,_,_,actor,leave_id=await submitted(db)
        node=(await approvals.list_items(db,first,'pending'))[0]['node_id']
        before=await db.scalar(select(func.count()).select_from(OAWorkflowEvent).where(OAWorkflowEvent.tenant_id==actor.tenant_id))
        flush=db.flush
        async def fail(*args,**kwargs):
            model={'event':OAWorkflowEvent,'outbox':OAWorkflowOutbox,'ledger':OALeaveLedger}[failure]
            if any(isinstance(row,model) for row in db.new): raise RuntimeError('injected '+failure)
            return await flush(*args,**kwargs)
        monkeypatch.setattr(db,'flush',fail)
        command=DecideNodeCommand(operation_id='finish',expected_revision=1,action='approve')
        with pytest.raises(RuntimeError): await approvals.decide(db,first,node,command)
        monkeypatch.setattr(db,'flush',flush)
        await db.commit()
        assert (await db.get(OALeave,leave_id,populate_existing=True)).state=='IN_REVIEW'
        assert (await db.get(OAWorkflowNode,node,populate_existing=True)).state=='ACTIVE'
        assert (await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node))).state=='PENDING'
        balance=await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
        assert (balance.used,balance.reserved)==(0,1)
        assert await db.scalar(select(func.count()).select_from(OAWorkflowEvent).where(OAWorkflowEvent.tenant_id==actor.tenant_id))==before
        assert (await approvals.decide(db,first,node,command)).result['state']=='APPROVED'
        await db.commit()
