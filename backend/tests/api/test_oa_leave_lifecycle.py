import pytest
from sqlalchemy import select, func

from app.core.errors import AppException
from app.models.oa_leave import OALeaveVersion, OALeaveBalance
from app.models.oa_workflow import OAWorkflowInstance
from app.schemas.oa_leave import NormalizedLeaveFields, LeaveDraftCreate, LeaveDraftPatch, SubmitLeaveCommand
from tests.oa_support import oa_db, seed
from tests.unit.test_oa_workflow_definition import definition


def fields(start='2026-10-20',end='2026-10-20',**kwargs):
    return NormalizedLeaveFields(leave_type=kwargs.pop('leave_type','annual'),start_date=start,end_date=end,reason='测试请假',**kwargs)


async def setup_leave(db, *, manager=True, package=None):
    from app.services import oa_workflow_service as workflows
    from app.schemas.oa_workflow import WorkflowSave, PublishWorkflow
    admin = await seed(db,resources=['workflow','approval','leave_balance','workflow_admin','leave'])
    applicant = await seed(db,tenant=admin.tenant_id,department=admin.depts[0],resources=['leave','leave_balance'],scope='self',manager=admin.user_id if manager else None)
    await db.commit()
    saved = await workflows.save_definition(db,admin,WorkflowSave(operation_id='save',department_id=admin.depts[0],code='leave',name='请假',definition=package or definition()))
    await workflows.publish_definition(db,admin,saved['id'],PublishWorkflow(operation_id='publish',expected_revision=1))
    await db.commit()
    return admin,applicant,saved['id']


async def test_draft_owner_revision_and_submit_replay(oa_db):
    from app.services import oa_leave_service as service, oa_balance_service as balances
    from app.schemas.oa_leave import BalanceAdjustment
    async with oa_db() as db:
        admin,actor,workflow = await setup_leave(db)
        draft = await service.create_draft(db,actor,LeaveDraftCreate(operation_id='create',workflow_definition_id=workflow,fields=fields()))
        await db.commit()
        with pytest.raises(AppException): await service.update_draft(db,admin,draft.result['id'],LeaveDraftPatch(operation_id='bad',expected_revision=1,fields=fields()))
        await db.rollback()
        changed = await service.update_draft(db,actor,draft.result['id'],LeaveDraftPatch(operation_id='edit',expected_revision=1,fields=fields('2026-10-20','2026-10-21')))
        await db.commit()
        assert changed.result['revision'] == 2
        with pytest.raises(AppException): await service.update_draft(db,actor,draft.result['id'],LeaveDraftPatch(operation_id='stale',expected_revision=1,fields=fields()))
        await db.rollback()
        await balances.adjust(db,admin,BalanceAdjustment(operation_id='quota',expected_revision=0,user_id=actor.user_id,leave_type='annual',year=2026,total=5,reason='测试初始额度'))
        await db.commit()
        command = SubmitLeaveCommand(operation_id='submit',expected_revision=2,requested_submission_version=1)
        submitted = await service.submit(db,actor,draft.result['id'],command)
        await db.commit()
        replay = await service.submit(db,actor,draft.result['id'],command)
        assert replay.replayed and submitted.result['state']=='IN_REVIEW'
        assert await db.scalar(select(func.count()).select_from(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id==actor.tenant_id)) == 1
        balance = await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
        assert (balance.used,balance.reserved) == (0,2)
        with pytest.raises(AppException): await service.update_draft(db,actor,draft.result['id'],LeaveDraftPatch(operation_id='inflight',expected_revision=3,fields=fields()))


async def test_invalid_material_no_partial_version_and_missing_route_pauses(oa_db):
    from app.services import oa_leave_service as service, oa_balance_service as balances
    from app.schemas.oa_leave import BalanceAdjustment
    async with oa_db() as db:
        admin,actor,workflow = await setup_leave(db,manager=False)
        draft = await service.create_draft(db,actor,LeaveDraftCreate(operation_id='create',workflow_definition_id=workflow,fields=fields(attachment_ids=['missing'])))
        await balances.adjust(db,admin,BalanceAdjustment(operation_id='quota',expected_revision=0,user_id=actor.user_id,leave_type='annual',year=2026,total=5,reason='测试'))
        await db.commit()
        with pytest.raises(AppException): await service.submit(db,actor,draft.result['id'],SubmitLeaveCommand(operation_id='bad',expected_revision=1,requested_submission_version=1))
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(OALeaveVersion).where(OALeaveVersion.tenant_id==actor.tenant_id)) == 0
        await service.update_draft(db,actor,draft.result['id'],LeaveDraftPatch(operation_id='fix',expected_revision=1,fields=fields()))
        await db.commit()
        paused = await service.submit(db,actor,draft.result['id'],SubmitLeaveCommand(operation_id='submit',expected_revision=2,requested_submission_version=1))
        await db.commit()
        assert paused.result['state'] == 'PAUSED'
        balance = await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
        assert balance.reserved == 1
