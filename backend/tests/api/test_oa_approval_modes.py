from copy import deepcopy
import pytest
from sqlalchemy import select
from app.core.errors import AppException
from app.models.oa_leave import OALeaveBalance,OALeave
from app.models.oa_workflow import OAWorkflowSeat,OAWorkflowNode
from app.schemas.oa_leave import LeaveDraftCreate,SubmitLeaveCommand,BalanceAdjustment,OACommand
from tests.oa_support import oa_db,seed
from tests.api.test_oa_leave_lifecycle import setup_leave,fields
from tests.unit.test_oa_workflow_definition import definition


async def submitted(db,*,mode='single',cc=False):
    from app.services import oa_workflow_service as workflows,oa_leave_service as leaves,oa_balance_service as balances
    from app.schemas.oa_workflow import WorkflowSave,PublishWorkflow
    admin,actor,workflow=await setup_leave(db)
    second=await seed(db,tenant=actor.tenant_id,department=actor.depts[0],resources=['approval'],scope='self')
    copied=await seed(db,tenant=actor.tenant_id,department=actor.depts[0],resources=['approval'],scope='self')
    await db.commit()
    value=definition()
    value['nodes'][0]['mode']=mode
    value['nodes'][0]['selector']=dict(kind='users',user_ids=[admin.user_id] if mode=='single' else [admin.user_id,second.user_id])
    if cc:
        value['nodes'][0]['next_id']='cc'
        value['nodes'].insert(1,dict(id='cc',kind='cc',selector=dict(kind='users',user_ids=[copied.user_id]),next_id='end'))
    await workflows.save_definition(db,admin,WorkflowSave(operation_id='mode',department_id=admin.depts[0],code='leave',name='请假',definition=value,expected_revision=2),workflow)
    await workflows.publish_definition(db,admin,workflow,PublishWorkflow(operation_id='pub2',expected_revision=3))
    await db.commit()
    await balances.adjust(db,admin,BalanceAdjustment(operation_id='quota',expected_revision=0,user_id=actor.user_id,leave_type='annual',year=2026,total=5,reason='测试'))
    await db.commit()
    draft=await leaves.create_draft(db,actor,LeaveDraftCreate(operation_id='create',workflow_definition_id=workflow,fields=fields()))
    await db.commit()
    result=await leaves.submit(db,actor,draft.result['id'],SubmitLeaveCommand(operation_id='submit',expected_revision=1,requested_submission_version=1))
    await db.commit()
    return admin,second,copied,actor,result.result['id']


@pytest.mark.parametrize('mode',['single','all','any'])
async def test_approval_modes_once_only_and_minimal_history(oa_db,mode):
    from app.services import oa_approval_service as approvals
    from app.schemas.oa_workflow import DecideNodeCommand
    async with oa_db() as db:
        first,second,copied,actor,leave_id=await submitted(db,mode=mode,cc=True)
        pending=await approvals.list_items(db,first,'pending')
        assert len(pending)==1
        item=pending[0]
        context=await approvals.node_context(db,first,item['node_id'])
        assert 'balance' not in context and 'versions' not in context
        with pytest.raises(AppException): await approvals.node_context(db,actor,item['node_id'])
        await db.rollback()
        command=DecideNodeCommand(operation_id='approve',expected_revision=1,action='approve',note='同意')
        result=await approvals.decide(db,first,item['node_id'],command)
        await db.commit()
        assert result.result['state']==('IN_REVIEW' if mode=='all' else 'APPROVED')
        if mode=='all':
            await approvals.decide(db,second,item['node_id'],DecideNodeCommand(operation_id='second',expected_revision=2,action='approve',note='同意'))
            await db.commit()
        assert (await db.get(OALeave,leave_id,populate_existing=True)).state=='APPROVED'
        replay=await approvals.decide(db,first,item['node_id'],command)
        assert replay.replayed
        await db.commit()
        balance=await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
        assert (balance.used,balance.reserved)==(1,0)
        assert await approvals.list_items(db,first,'pending')==[]
        done=await approvals.list_items(db,first,'done')
        assert len(done)==1 and 'attachments' not in done[0] and 'fields' not in done[0]
        assert len(await approvals.list_items(db,copied,'cc'))==1
        with pytest.raises(AppException): await approvals.node_context(db,first,item['node_id'])


@pytest.mark.parametrize('action',['reject','return_for_correction'])
async def test_reject_and_structured_return_release_then_new_round(oa_db,action):
    from app.services import oa_approval_service as approvals,oa_leave_service as leaves
    from app.schemas.oa_workflow import DecideNodeCommand
    from app.schemas.oa_leave import LeaveDraftPatch
    async with oa_db() as db:
        first,_,_,actor,leave_id=await submitted(db)
        node=(await approvals.list_items(db,first,'pending'))[0]['node_id']
        result=await approvals.decide(db,first,node,DecideNodeCommand(operation_id='reject',expected_revision=1,action=action,note='请补充说明',corrections=['reason'] if action=='return_for_correction' else []))
        await db.commit()
        assert result.result['state']=='REJECTED'
        balance=await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
        assert (balance.used,balance.reserved)==(0,0)
        await leaves.update_draft(db,actor,leave_id,LeaveDraftPatch(operation_id='fix',expected_revision=3,fields=fields('2026-10-21','2026-10-21')))
        await db.commit()
        new=await leaves.submit(db,actor,leave_id,SubmitLeaveCommand(operation_id='resubmit',expected_revision=4,requested_submission_version=2))
        await db.commit()
        assert new.result['submission_version']==2
        detail=await leaves.detail(db,actor,leave_id)
        assert len(detail['versions'])==2 and detail['versions'][0]['fields']['start_date']=='2026-10-20'
        assert detail['history'][0]['action']==action
        assert detail['history'][0]['reason_code']
        assert detail['history'][0]['corrections']==(['reason'] if action=='return_for_correction' else [])


@pytest.mark.parametrize('mode',['any','all'])
async def test_one_rejection_terminates_and_other_seat_cannot_decide(oa_db,mode):
    from app.services import oa_approval_service as approvals
    from app.schemas.oa_workflow import DecideNodeCommand
    async with oa_db() as db:
        first,second,_,actor,leave_id=await submitted(db,mode=mode)
        node=(await approvals.list_items(db,first,'pending'))[0]['node_id']
        await approvals.decide(db,first,node,DecideNodeCommand(operation_id='reject',expected_revision=1,action='reject',note='材料不完整'))
        await db.commit()
        assert await approvals.list_items(db,second,'pending')==[]
        with pytest.raises(AppException):
            await approvals.decide(db,second,node,DecideNodeCommand(operation_id='late',expected_revision=1,action='approve'))
        await db.rollback()
        assert (await db.get(OALeave,leave_id,populate_existing=True)).state=='REJECTED'


async def test_sequential_node_materials_and_future_qualification_change(oa_db):
    from app.models.identity import OAMembership,OADepartment
    from app.services import oa_approval_service as approvals,oa_workflow_service as workflows,oa_leave_service as leaves
    from app.schemas.oa_workflow import WorkflowSave,PublishWorkflow,DecideNodeCommand
    async with oa_db() as db:
        first,second,_,actor,leave_id=await submitted(db)
        # Start a new submission with two sequential approvals.
        await leaves.withdraw(db,actor,leave_id,OACommand(operation_id='withdraw',expected_revision=2))
        await db.commit()
        row=await db.get(OALeave,leave_id)
        value=definition()
        value['nodes'][0]['selector']=dict(kind='users',user_ids=[first.user_id])
        value['nodes'][0]['next_id']='next'
        value['nodes'].insert(1,dict(id='next',kind='approval',mode='single',selector=dict(kind='users',user_ids=[second.user_id]),next_id='end'))
        await workflows.save_definition(db,first,WorkflowSave(operation_id='seq',department_id=first.depts[0],code='leave',name='请假',definition=value,expected_revision=4),row.workflow_definition_id)
        await workflows.publish_definition(db,first,row.workflow_definition_id,PublishWorkflow(operation_id='seqpub',expected_revision=5))
        await db.commit()
        await leaves.submit(db,actor,leave_id,SubmitLeaveCommand(operation_id='round2',expected_revision=3,requested_submission_version=2))
        await db.commit()
        assert await approvals.list_items(db,second,'pending')==[]
        first_node=(await approvals.list_items(db,first,'pending'))[0]['node_id']
        await approvals.decide(db,first,first_node,DecideNodeCommand(operation_id='next',expected_revision=1,action='approve',approval_note='已核对'))
        await db.commit()
        second_node=(await approvals.list_items(db,second,'pending'))[0]['node_id']
        assert (await approvals.node_context(db,second,second_node))['approval_notes'][0]['note']=='已核对'
        with pytest.raises(AppException): await approvals.node_context(db,first,first_node)
        await db.rollback()
        await approvals.decide(db,second,second_node,DecideNodeCommand(operation_id='last',expected_revision=1,action='approve'))
        await db.commit()
        assert (await db.get(OALeave,leave_id,populate_existing=True)).state=='APPROVED'


async def test_replay_denied_after_current_seat_permission_removed(oa_db):
    from sqlalchemy import delete
    from app.models.identity import OAUserRole,OARolePermission
    from app.services import oa_approval_service as approvals
    from app.schemas.oa_workflow import DecideNodeCommand
    async with oa_db() as db:
        first,_,_,_,_=await submitted(db)
        node=(await approvals.list_items(db,first,'pending'))[0]['node_id']
        command=DecideNodeCommand(operation_id='done',expected_revision=1,action='approve')
        await approvals.decide(db,first,node,command)
        await db.commit()
        roles=select(OAUserRole.role_id).where(OAUserRole.user_id==first.user_id)
        await db.execute(delete(OARolePermission).where(OARolePermission.role_id.in_(roles)))
        await db.commit()
        with pytest.raises(AppException): await approvals.decide(db,first,node,command)


async def test_withdraw_archive_and_critical_edit_rejected(oa_db):
    from app.services import oa_leave_service as leaves,oa_approval_service as approvals
    from app.schemas.oa_workflow import DecideNodeCommand
    async with oa_db() as db:
        first,_,_,actor,leave_id=await submitted(db)
        item=(await approvals.list_items(db,first,'pending'))[0]
        result=await leaves.withdraw(db,actor,leave_id,OACommand(operation_id='withdraw',expected_revision=2))
        await db.commit()
        assert result.result['state']=='CANCELLED'
        with pytest.raises(AppException): await approvals.decide(db,first,item['node_id'],DecideNodeCommand(operation_id='late',expected_revision=1,action='approve',note='同意'))
        await db.rollback()
        archive=await leaves.archive(db,actor,leave_id,OACommand(operation_id='archive',expected_revision=3))
        await db.commit()
        assert archive.result['state']=='CANCELLED' and archive.result['archived_at']
