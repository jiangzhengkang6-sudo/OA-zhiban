import pytest
from sqlalchemy import select, func
from app.core.errors import AppException
from app.models.identity import OADepartment
from app.models.oa_workflow import OAWorkflowOperation, OAWorkflowEvent, OAWorkflowOutbox
from tests.oa_support import oa_db, seed


async def test_idempotency_and_atomic_audit_failure(oa_db, monkeypatch):
    from app.services import oa_command_service as service
    from app.services.oa_access_service import OAAccessTarget
    async with oa_db() as db:
        actor = await seed(db, resources=['workflow'])
        await db.commit()
        command = service.OACommand(kind='test', target_id=actor.depts[0], target_version='1', operation_id='operation',
            payload={'value': 2}, resource='workflow', target=OAAccessTarget(actor.tenant_id, department_id=actor.depts[0]))
        calls = []
        async def handler(operation):
            calls.append(1)
            dept = await db.get(OADepartment, actor.depts[0])
            dept.name = 'changed'
            return service.CommandOutcome(result={'revision': 2}, recipients=[actor.user_id])
        result = await service.run_command(db, actor, command, handler)
        await db.commit()
        assert not result.replayed
        replay = await service.run_command(db, actor, command, handler)
        assert replay.replayed and len(calls) == 1
        await db.commit()
        command.payload = {'value': 3}
        with pytest.raises(AppException): await service.run_command(db, actor, command, handler)
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(OAWorkflowEvent).where(OAWorkflowEvent.tenant_id==actor.tenant_id)) == 1
        assert await db.scalar(select(func.count()).select_from(OAWorkflowOutbox).where(OAWorkflowOutbox.tenant_id==actor.tenant_id)) == 1
        async def broken(*args): raise RuntimeError('injected audit failure')
        monkeypatch.setattr(service, 'persist_events', broken)
        command.operation_id = 'second'
        async def failing_handler(operation):
            (await db.get(OADepartment, actor.depts[0])).name = 'must rollback'
            return service.CommandOutcome(result={'revision': 3})
        with pytest.raises(RuntimeError): await service.run_command(db, actor, command, failing_handler)
        await db.commit()
        assert (await db.get(OADepartment, actor.depts[0], populate_existing=True)).name == 'changed'
        assert await db.scalar(select(func.count()).select_from(OAWorkflowOperation).where(OAWorkflowOperation.tenant_id==actor.tenant_id)) == 1


async def test_replay_rechecks_current_permission(oa_db):
    from app.models.identity import OAUserRole, OARolePermission
    from app.services import oa_command_service as service
    from app.services.oa_access_service import OAAccessTarget
    async with oa_db() as db:
        actor = await seed(db,resources=['workflow'])
        await db.commit()
        command = service.OACommand(kind='test',target_id=actor.depts[0],target_version='1',operation_id='retry',
            payload={},resource='workflow',target=OAAccessTarget(actor.tenant_id,department_id=actor.depts[0]))
        async def handler(operation): return service.CommandOutcome(result={'revision':1})
        await service.run_command(db,actor,command,handler)
        await db.commit()
        role_id = await db.scalar(select(OAUserRole.role_id).where(OAUserRole.user_id==actor.user_id))
        from sqlalchemy import delete
        await db.execute(delete(OARolePermission).where(OARolePermission.role_id==role_id))
        await db.commit()
        with pytest.raises(AppException) as error:
            await service.run_command(db,actor,command,handler)
        assert error.value.http_status == 403


async def test_outbox_failure_rolls_back_business_and_audit(oa_db,monkeypatch):
    from app.services import oa_command_service as service
    from app.services.oa_access_service import OAAccessTarget
    async with oa_db() as db:
        actor = await seed(db,resources=['workflow'])
        await db.commit()
        original = (await db.get(OADepartment,actor.depts[0])).name
        command = service.OACommand(kind='test',target_id=actor.depts[0],target_version='1',operation_id='outbox',
            payload={},resource='workflow',target=OAAccessTarget(actor.tenant_id,department_id=actor.depts[0]))
        flush = db.flush
        async def fail_outbox(*args,**kwargs):
            if any(isinstance(row,OAWorkflowOutbox) for row in db.new):
                raise RuntimeError('injected outbox failure')
            return await flush(*args,**kwargs)
        monkeypatch.setattr(db,'flush',fail_outbox)
        async def handler(operation):
            (await db.get(OADepartment,actor.depts[0])).name = 'should rollback'
            return service.CommandOutcome(result={'revision':1},recipients=[actor.user_id])
        with pytest.raises(RuntimeError): await service.run_command(db,actor,command,handler)
        await db.commit()
        assert (await db.get(OADepartment,actor.depts[0],populate_existing=True)).name == original
        for model in [OAWorkflowOperation,OAWorkflowEvent,OAWorkflowOutbox]:
            assert await db.scalar(select(func.count()).select_from(model).where(model.tenant_id==actor.tenant_id)) == 0


async def test_outbox_excludes_recipient_without_current_read_permission(oa_db):
    from app.services import oa_command_service as service
    from app.services.oa_access_service import OAAccessTarget
    async with oa_db() as db:
        actor = await seed(db,resources=['workflow'])
        other = await seed(db,tenant=actor.tenant_id,department=actor.depts[0])
        await db.commit()
        command = service.OACommand(kind='test',target_id=actor.depts[0],target_version='1',operation_id='notify',
            payload={},resource='workflow',target=OAAccessTarget(actor.tenant_id,department_id=actor.depts[0]))
        async def handler(operation): return service.CommandOutcome(result={},recipients=[actor.user_id,other.user_id])
        await service.run_command(db,actor,command,handler)
        await db.commit()
        assert list((await db.scalars(select(OAWorkflowOutbox.recipient_id).where(OAWorkflowOutbox.tenant_id==actor.tenant_id))).all()) == [actor.user_id]


async def test_submit_audit_failure_rolls_back_version_nodes_and_balance(oa_db,monkeypatch):
    from app.services import oa_leave_service as leaves, oa_balance_service as balances, oa_command_service as commands
    from app.models.oa_leave import OALeave,OALeaveVersion,OALeaveBalance,OALeaveLedger
    from app.models.oa_workflow import OAWorkflowInstance,OAWorkflowNode,OAWorkflowSeat
    from app.schemas.oa_leave import BalanceAdjustment,LeaveDraftCreate,SubmitLeaveCommand
    from tests.api.test_oa_leave_lifecycle import setup_leave,fields
    async with oa_db() as db:
        admin,actor,workflow = await setup_leave(db)
        draft = await leaves.create_draft(db,actor,LeaveDraftCreate(operation_id='create',workflow_definition_id=workflow,fields=fields()))
        await balances.adjust(db,admin,BalanceAdjustment(operation_id='quota',expected_revision=0,user_id=actor.user_id,leave_type='annual',year=2026,total=5,reason='测试'))
        await db.commit()
        original = commands.persist_events
        async def fail(*args): raise RuntimeError('submit event failure')
        monkeypatch.setattr(commands,'persist_events',fail)
        payload=SubmitLeaveCommand(operation_id='submit',expected_revision=1,requested_submission_version=1)
        with pytest.raises(RuntimeError): await leaves.submit(db,actor,draft.result['id'],payload)
        await db.commit()
        assert (await db.get(OALeave,draft.result['id'],populate_existing=True)).state=='DRAFT'
        for model in [OALeaveVersion,OAWorkflowInstance,OAWorkflowNode,OAWorkflowSeat]:
            assert await db.scalar(select(func.count()).select_from(model).where(model.tenant_id==actor.tenant_id))==0
        assert await db.scalar(select(OALeaveBalance.reserved).where(OALeaveBalance.user_id==actor.user_id))==0
        assert await db.scalar(select(func.count()).select_from(OALeaveLedger).where(OALeaveLedger.tenant_id==actor.tenant_id))==1
        monkeypatch.setattr(commands,'persist_events',original)
        assert (await leaves.submit(db,actor,draft.result['id'],payload)).result['state']=='IN_REVIEW'
        await db.commit()
