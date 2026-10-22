import pytest
from sqlalchemy import select,update
from app.core.errors import AppException
from app.models.identity import OAUser
from app.models.oa_leave import OALeave,OALeaveVersion
from app.models.oa_workflow import OAWorkflowSeat,OAWorkflowNode,OAWorkflowInstance
from tests.oa_support import oa_db,seed
from tests.api.test_oa_approval_modes import submitted


async def test_disabled_seat_transfer_keeps_original_and_global_handoff(oa_db):
    from app.services import oa_handoff_service as handoff,oa_approval_service as approvals
    from app.schemas.oa_workflow import SeatHandoffCommand,DecideNodeCommand
    async with oa_db() as db:
        original,_,replacement,actor,leave_id=await submitted(db)
        admin=await seed(db,tenant=actor.tenant_id,department=actor.depts[0],resources=['workflow_admin'])
        await db.commit()
        node=(await approvals.list_items(db,original,'pending'))[0]['node_id']
        seat_id=await db.scalar(select(OAWorkflowSeat.id).where(OAWorkflowSeat.node_id==node))
    async with oa_db() as db:
        await db.execute(update(OAUser).where(OAUser.id==original.user_id).values(status='disabled',handoff_pending=True))
        await db.commit()
    async with oa_db() as db:
        payload=SeatHandoffCommand(operation_id='transfer',expected_revision=1,target_user_id=replacement.user_id,reason='离职待办交接')
        result=await handoff.transfer(db,admin,seat_id,payload)
        await db.commit()
        assert result.result['remaining_m2_seats']==0 and result.result['m2_handoff_complete']
        assert (await db.get(OAUser,original.user_id)).handoff_pending
        seat=await db.get(OAWorkflowSeat,seat_id)
        assert seat.original_user_id==original.user_id and seat.effective_user_id==replacement.user_id
        assert len(await approvals.list_items(db,replacement,'pending'))==1
        assert (await handoff.transfer(db,admin,seat_id,payload)).replayed
        await db.commit()
        with pytest.raises(AppException): await approvals.node_context(db,original,node)
        await db.rollback()
        result=await approvals.decide(db,replacement,node,DecideNodeCommand(operation_id='approve',expected_revision=2,action='approve'))
        await db.commit()
        assert result.result['state']=='APPROVED'


@pytest.mark.parametrize('target',['applicant','duplicate','foreign','other_department','unqualified'])
async def test_invalid_handoff_is_atomic(oa_db,target):
    from app.services import oa_handoff_service as handoff,oa_approval_service as approvals
    from app.schemas.oa_workflow import SeatHandoffCommand
    async with oa_db() as db:
        first,second,_,actor,leave_id=await submitted(db,mode='all')
        foreign=await seed(db,resources=['approval'])
        other=await seed(db,tenant=actor.tenant_id,resources=['approval'])
        unqualified=await seed(db,tenant=actor.tenant_id,department=actor.depts[0])
        await db.commit()
        node=(await approvals.list_items(db,first,'pending'))[0]['node_id']
        seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node,OAWorkflowSeat.effective_user_id==first.user_id))
        target_id={'applicant':actor.user_id,'duplicate':second.user_id,'foreign':foreign.user_id,'other_department':other.user_id,'unqualified':unqualified.user_id}[target]
        with pytest.raises(AppException):
            await handoff.transfer(db,first,seat.id,SeatHandoffCommand(operation_id='bad',expected_revision=1,target_user_id=target_id,reason='测试'))
        await db.commit()
        assert (await db.get(OAWorkflowSeat,seat.id,populate_existing=True)).effective_user_id==first.user_id
        assert (await db.get(OAWorkflowNode,node,populate_existing=True)).revision==1


async def test_resume_uses_frozen_route_and_explicit_replacement(oa_db):
    from app.services import oa_handoff_service as handoff,oa_approval_service as approvals
    from app.schemas.oa_workflow import RouteResumeCommand
    async with oa_db() as db:
        first,_,replacement,actor,leave_id=await submitted(db)
        node=(await approvals.list_items(db,first,'pending'))[0]['node_id']
        row=await db.get(OAWorkflowNode,node)
        instance=await db.get(OAWorkflowInstance,row.instance_id)
        instance.state='PAUSED'
        instance.pause_reason='测试暂停'
        (await db.get(OALeave,leave_id)).state='PAUSED'
        seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node))
        await db.commit()
        result=await handoff.resume(db,first,instance.id,RouteResumeCommand(operation_id='resume',expected_revision=1,
            replacements=[dict(seat_id=seat.id,target_user_id=replacement.user_id)],reason='指定新办理人并恢复'))
        await db.commit()
        assert result.result['state']=='IN_REVIEW' and result.result['route_revision']==2
        assert (await approvals.list_items(db,replacement,'pending'))[0]['node_id']==node


async def test_resume_rejects_single_role_resolving_to_multiple_seats(oa_db):
    from app.models.identity import OAUserRole
    from app.schemas.oa_workflow import WorkflowSave,PublishWorkflow,RouteResumeCommand
    from app.schemas.oa_leave import LeaveDraftCreate,SubmitLeaveCommand
    from app.services import oa_handoff_service as handoff,oa_workflow_service as workflows,oa_leave_service as leaves
    from tests.unit.test_oa_workflow_definition import definition
    from tests.api.test_oa_leave_lifecycle import fields
    async with oa_db() as db:
        first,second,_,actor,_=await submitted(db)
        role=await db.scalar(select(OAUserRole.role_id).where(OAUserRole.tenant_id==actor.tenant_id,OAUserRole.user_id==first.user_id))
        db.add(OAUserRole(tenant_id=actor.tenant_id,user_id=second.user_id,role_id=role))
        value=definition()
        value['nodes'][0]['selector']=dict(kind='role',role_id=role)
        saved=await workflows.save_definition(db,first,WorkflowSave(operation_id='role',department_id=first.depts[0],
            code='role-single',name='单签角色',definition=value))
        await db.commit()
        await workflows.publish_definition(db,first,saved['id'],PublishWorkflow(operation_id='publish',expected_revision=1))
        await db.commit()
        draft=await leaves.create_draft(db,actor,LeaveDraftCreate(operation_id='draft-role',workflow_definition_id=saved['id'],
            fields=fields('2026-10-25','2026-10-25')))
        await db.commit()
        result=await leaves.submit(db,actor,draft.result['id'],SubmitLeaveCommand(operation_id='submit-role',expected_revision=1,requested_submission_version=1))
        await db.commit()
        assert result.result['state']=='PAUSED'
        instance=await db.scalar(select(OAWorkflowInstance).join(OALeaveVersion,OAWorkflowInstance.leave_version_id==OALeaveVersion.id)
            .where(OALeaveVersion.leave_id==draft.result['id']))
        with pytest.raises(AppException):
            await handoff.resume(db,first,instance.id,RouteResumeCommand(operation_id='bad-resume',expected_revision=1,reason='人数未修正'))
        await db.commit()
        assert (await db.get(OAWorkflowInstance,instance.id,populate_existing=True)).state=='PAUSED'
