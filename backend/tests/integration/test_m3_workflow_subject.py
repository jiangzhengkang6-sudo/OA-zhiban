from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, func
from app.core.errors import AppException
from app.models.oa_workflow import OAWorkflowInstance, OAWorkflowNode, OAWorkflowSeat, OAWorkflowEvent
from app.models.oa_leave import OALeaveLedger
from app.schemas.oa_workflow import DecideNodeCommand, SeatHandoffCommand
from tests.oa_support import oa_db, seed
from tests.api.test_oa_approval_modes import submitted


async def reimbursement(db):
    from app.models.oa_reimbursement import OAReimbursement, OAReimbursementVersion
    from app.models.oa_leave import OALeave, OALeaveVersion
    first, second, _, actor, leave_id = await submitted(db)
    admin = first
    leave = await db.get(OALeave, leave_id)
    lv = await db.scalar(select(OALeaveVersion).where(OALeaveVersion.leave_id == leave_id))
    original = await db.scalar(select(OAWorkflowInstance).where(OAWorkflowInstance.leave_version_id == lv.id))
    row = OAReimbursement(tenant_id=actor.tenant_id, business_no='R1', applicant_id=actor.user_id,
        department_id=leave.department_id, workflow_definition_id=leave.workflow_definition_id,
        fields=dict(purpose='差旅报销',amount='1000.01',currency='CNY'),revision=1,submission_version=1,state='IN_REVIEW')
    db.add(row)
    await db.flush()
    version = OAReimbursementVersion(tenant_id=actor.tenant_id,reimbursement_id=row.id,version=1,
        workflow_version_id=lv.workflow_version_id,fields=row.fields,attachments=[],precheck={},differences={},
        amount_cents=100001,currency='CNY')
    db.add(version)
    await db.flush()
    instance = OAWorkflowInstance(tenant_id=actor.tenant_id,scene='reimbursement',reimbursement_version_id=version.id,
        route_snapshot=original.route_snapshot,state='IN_REVIEW')
    db.add(instance)
    await db.flush()
    old_node = await db.scalar(select(OAWorkflowNode).where(OAWorkflowNode.instance_id==original.id))
    old_seat = await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==old_node.id))
    node = OAWorkflowNode(tenant_id=actor.tenant_id,instance_id=instance.id,ordinal=0,node_key=old_node.node_key,
        kind='approval',mode='single',state='ACTIVE',due_at=datetime.now(timezone.utc)+timedelta(hours=1))
    db.add(node)
    await db.flush()
    db.add(OAWorkflowSeat(tenant_id=actor.tenant_id,node_id=node.id,original_user_id=first.user_id,
        effective_user_id=first.user_id,eligibility=old_seat.eligibility,state='PENDING'))
    await db.commit()
    return first, second, admin, actor, row, version, instance, node


async def test_subject_resolution_and_approval_keep_quota_leave_only(oa_db):
    from app.services.oa_workflow_subject import resolve_subject
    from app.services import oa_approval_service as approvals
    async with oa_db() as db:
        first, _, _, actor, row, version, instance, node = await reimbursement(db)
        subject = await resolve_subject(db, actor, instance)
        assert (subject.scene,subject.object_id,subject.version_id,subject.owner_id)==('reimbursement',row.id,version.id,actor.user_id)
        pending = next(item for item in await approvals.list_items(db,first,'pending') if item['node_id']==node.id)
        assert pending['scene']=='reimbursement' and pending['object_id']==row.id and pending['leave_id'] is None
        before = await db.scalar(select(func.count()).select_from(OALeaveLedger).where(OALeaveLedger.tenant_id==actor.tenant_id))
        result = await approvals.decide(db,first,node.id,DecideNodeCommand(operation_id='r-approve',expected_revision=1,action='approve'))
        await db.commit()
        assert result.result['state']=='APPROVED' and row.state=='APPROVED'
        assert await db.scalar(select(func.count()).select_from(OALeaveLedger).where(OALeaveLedger.tenant_id==actor.tenant_id))==before
        event=await db.scalar(select(OAWorkflowEvent).where(OAWorkflowEvent.target_id==node.id))
        assert event.trace_id and event.target_version=='1'
        assert event.changes=={'before':{'state':'IN_REVIEW'},'after':{'state':'APPROVED'}}


async def test_reimbursement_administration_and_timers_are_typed(oa_db):
    from app.services import oa_handoff_service as handoff, oa_workflow_scheduler as timers
    async with oa_db() as db:
        first, second, admin, actor, row, version, instance, node = await reimbursement(db)
        listed=await handoff.list_instances(db,admin)
        assert any(item['scene']=='reimbursement' and item['object_id']==row.id for item in listed)
        assert await timers.reconciliation_issues(db,row)==[]
        assert (await timers.reconcile(db,admin))['ok']
        result=await timers.scan(db,actor=admin,now=node.due_at-timedelta(minutes=10))
        await db.commit()
        assert result['processed']>=1 and not result['errors']
        seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node.id))
        outcome=await handoff.transfer(db,admin,seat.id,SeatHandoffCommand(operation_id='r-transfer',
            expected_revision=node.revision,target_user_id=second.user_id,reason='人员交接'))
        await db.commit()
        assert outcome.result['remaining_m2_seats']>=1


async def test_subject_cross_tenant_is_rejected(oa_db):
    from app.services.oa_workflow_subject import resolve_subject
    from tests.oa_support import seed
    async with oa_db() as db:
        *_, instance, node=await reimbursement(db)
        other=await seed(db,resources=['approval'])
        with pytest.raises(AppException):
            await resolve_subject(db,other,instance)


@pytest.mark.parametrize('failure',['event','outbox'])
async def test_reimbursement_approval_event_failure_is_atomic(oa_db,monkeypatch,failure):
    from app.services import oa_approval_service as approvals
    from app.models.oa_workflow import OAWorkflowOutbox, OAWorkflowOperation
    async with oa_db() as db:
        first, _, _, actor, row, _, instance, node=await reimbursement(db)
        # The next approval seat yields an authorized outbox recipient.
        next_node=OAWorkflowNode(tenant_id=actor.tenant_id,instance_id=instance.id,ordinal=1,
            node_key='review2',kind='approval',mode='single',state='WAITING')
        db.add(next_node)
        await db.flush()
        seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node.id))
        db.add(OAWorkflowSeat(tenant_id=actor.tenant_id,node_id=next_node.id,original_user_id=first.user_id,
            effective_user_id=first.user_id,eligibility=seat.eligibility,state='PENDING'))
        instance.route_snapshot=[*instance.route_snapshot,instance.route_snapshot[0]]
        await db.commit()
        node_id,instance_id=node.id,instance.id
        flush=db.flush
        async def fail(*args,**kwargs):
            model=OAWorkflowEvent if failure=='event' else OAWorkflowOutbox
            if any(isinstance(item,model) for item in db.new): raise RuntimeError('injected '+failure)
            return await flush(*args,**kwargs)
        monkeypatch.setattr(db,'flush',fail)
        with pytest.raises(RuntimeError,match='injected'):
            await approvals.decide(db,first,node.id,DecideNodeCommand(operation_id='fail-'+failure,expected_revision=1,action='approve'))
        monkeypatch.setattr(db,'flush',flush)
        await db.commit()
        assert (await db.get(OAWorkflowNode,node_id,populate_existing=True)).state=='ACTIVE'
        assert (await db.get(OAWorkflowInstance,instance_id,populate_existing=True)).state=='IN_REVIEW'
        assert await db.scalar(select(func.count()).select_from(OAWorkflowOperation).where(
            OAWorkflowOperation.tenant_id==actor.tenant_id,OAWorkflowOperation.operation_id=='fail-'+failure))==0
