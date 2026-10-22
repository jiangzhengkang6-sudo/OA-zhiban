import asyncio
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select,func
from app.core.errors import AppException
from app.models.identity import OAMembership
from app.models.oa_leave import OALeave,OALeaveBalance
from app.models.oa_workflow import OAWorkflowNode,OAWorkflowSeat,OAWorkflowInstance,OAWorkflowEvent,OAWorkflowOutbox
from app.schemas.oa_workflow import SeatHandoffCommand,DecideNodeCommand
from tests.oa_support import oa_db,seed
from tests.api.test_oa_approval_modes import submitted


@pytest.mark.parametrize('kind',['transfer','timer'])
async def test_management_and_last_decision_serialize(oa_db,kind):
    from app.services import oa_handoff_service as handoff,oa_approval_service as approvals,oa_workflow_scheduler as timers
    async with oa_db() as db:
        first,_,replacement,actor,leave_id=await submitted(db)
        node=await db.scalar(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id==actor.tenant_id))
        node_id=node.id
        seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node_id))
        seat_id=seat.id
        (await db.get(OAMembership,(actor.tenant_id,first.user_id))).manager_id=replacement.user_id
        node.due_at=datetime.now(timezone.utc)-timedelta(minutes=1)
        await db.commit()
    async def decision():
        async with oa_db() as db:
            try:
                result=await approvals.decide(db,first,node_id,DecideNodeCommand(operation_id='decide',expected_revision=1,action='approve'))
                await db.commit()
                return result
            except AppException:
                await db.rollback()
    async def management():
        async with oa_db() as db:
            try:
                if kind=='transfer':
                    result=await handoff.transfer(db,first,seat_id,SeatHandoffCommand(operation_id='transfer',expected_revision=1,
                        target_user_id=replacement.user_id,reason='交接'))
                else: result=await timers.scan(db,actor=first)
                await db.commit()
                return result
            except AppException:
                await db.rollback()
    await asyncio.gather(decision(),management())
    async with oa_db() as db:
        leave=await db.get(OALeave,leave_id)
        seat=await db.get(OAWorkflowSeat,seat_id)
        assert (leave.state,seat.effective_user_id,seat.state) in {
            ('APPROVED',first.user_id,'APPROVED'),('IN_REVIEW',replacement.user_id,'PENDING')}
        balance=await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
        assert (balance.used,balance.reserved)==((1,0) if leave.state=='APPROVED' else (0,1))
        if leave.state=='APPROVED':
            assert await db.scalar(select(func.count()).select_from(OAWorkflowEvent).where(
                OAWorkflowEvent.tenant_id==actor.tenant_id,OAWorkflowEvent.action.in_(['workflow.transfer','workflow.escalate'])))==0


@pytest.mark.parametrize('action',['transfer','timer'])
@pytest.mark.parametrize('failure',['event','outbox'])
async def test_handoff_and_timer_event_failure_roll_back(oa_db,monkeypatch,action,failure):
    from app.services import oa_handoff_service as handoff,oa_workflow_scheduler as timers
    async with oa_db() as db:
        first,_,replacement,actor,leave_id=await submitted(db)
        node=await db.scalar(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id==actor.tenant_id))
        node.due_at=datetime.now(timezone.utc)-timedelta(minutes=1)
        (await db.get(OAMembership,(actor.tenant_id,first.user_id))).manager_id=replacement.user_id
        await db.commit()
        node_id=node.id
        seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node_id))
        seat_id=seat.id
        flush=db.flush
        async def fail(*args,**kwargs):
            if any(isinstance(row,OAWorkflowEvent if failure=='event' else OAWorkflowOutbox) for row in db.new):
                raise RuntimeError('injected '+failure)
            return await flush(*args,**kwargs)
        monkeypatch.setattr(db,'flush',fail)
        command=SeatHandoffCommand(operation_id='transfer',expected_revision=1,target_user_id=replacement.user_id,reason='交接')
        if action=='transfer':
            with pytest.raises(RuntimeError): await handoff.transfer(db,first,seat_id,command)
        else:
            report=await timers.scan(db,actor=first)
            assert report['errors'] and report['processed']==0
        monkeypatch.setattr(db,'flush',flush)
        await db.commit()
        assert (await db.get(OAWorkflowNode,node_id,populate_existing=True)).revision==1
        assert (await db.get(OAWorkflowSeat,seat_id,populate_existing=True)).effective_user_id==first.user_id
        if action=='transfer': await handoff.transfer(db,first,seat_id,command)
        else: assert (await timers.scan(db,actor=first))['processed']==1
        await db.commit()


async def test_nudge_is_once_only_and_missing_authority_does_not_mutate(oa_db):
    from app.services import oa_workflow_scheduler as timers
    async with oa_db() as db:
        first,_,_,actor,_=await submitted(db)
        node=await db.scalar(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id==actor.tenant_id))
        now=datetime.now(timezone.utc)
        node.due_at=now+timedelta(minutes=1)
        await db.commit()
        assert (await timers.scan(db,actor=actor,now=now))['processed']==0
        assert (await timers.scan(db,actor=first,now=now))['processed']==1
        await db.commit()
        assert (await timers.scan(db,actor=first,now=now))['replayed']==1
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(OAWorkflowEvent).where(
            OAWorkflowEvent.tenant_id==actor.tenant_id,OAWorkflowEvent.action=='workflow.nudge'))==1


async def test_department_management_does_not_cross_scope_or_allow_chain_handoff(oa_db):
    from app.services import oa_handoff_service as handoff
    async with oa_db() as db:
        first,_,replacement,actor,_=await submitted(db)
        foreign=await seed(db,tenant=actor.tenant_id,resources=['workflow_admin'])
        await db.commit()
        assert await handoff.list_instances(db,foreign)==[]
        node=await db.scalar(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id==actor.tenant_id))
        seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node.id))
        seat_id=seat.id
        with pytest.raises(AppException): await handoff.candidates(db,foreign,seat_id)
        await db.rollback()
        await handoff.transfer(db,first,seat_id,SeatHandoffCommand(operation_id='first',expected_revision=1,target_user_id=replacement.user_id,reason='交接'))
        await db.commit()
        with pytest.raises(AppException):
            await handoff.transfer(db,first,seat_id,SeatHandoffCommand(operation_id='chain',expected_revision=2,target_user_id=first.user_id,reason='再次交接'))
