"""Exercise lifecycle handoff through real domain services in the isolated test DB."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from app.core.errors import AppException
from app.models.identity import OAUser, OAMembership, OAUserRole, OAAuthSession
from app.models.audit_event import AuditEvent
from app.models.agent_thread import AgentThread
from app.models.work_task import WorkTask
from app.models.work_task_batch import WorkTaskBatch
from app.models.work_task_event import WorkTaskEvent
from app.models.oa_ticket import OATicket, OATicketAssignmentRule
from app.models.oa_workflow import OAWorkflowSeat
from app.schemas.organization import MemberBatch, UserUpdate, HandoffCommand, HandoffComplete, DepartmentInput
from app.schemas.work_task import WorkTaskCommand
from app.schemas.oa_workflow import DecideNodeCommand
from app.services import organization_service as org, member_handoff_service as handoffs
from app.services import identity_service as identities, work_task_service as tasks, oa_approval_service as approvals
from tests.oa_support import oa_db, seed
from tests.api.test_oa_approval_modes import submitted


async def group(db):
    admin = await seed(db, resources=['organization','work_task','ticket','ticket_handle','ticket_admin','workflow_admin'])
    owner = await seed(db, tenant=admin.tenant_id, department=admin.depts[0], resources=['work_task','ticket_handle'])
    recipient = await seed(db, tenant=admin.tenant_id, department=admin.depts[0], resources=['work_task','ticket_handle'])
    await db.commit()
    return admin, owner, recipient


async def change(db, admin, user_id, **changes):
    row = await org._target(db, OAUser, user_id, admin.tenant_id)
    view = await org._user_view(db, row)
    return await org.update_user(db, admin, user_id, UserUpdate(**{k:view[k] for k in
        ('display_name','status','department_id','position_id','manager_id','role_ids')} | changes))


def batch(members, **changes):
    return MemberBatch(operation_id=uuid4().hex, members=[dict(user_id=m.user_id,expected_version=m.authorization_version) for m in members],
        changes=changes, reason='部门人员调整')


def transfer_command(inventory, item, recipient, **changes):
    return HandoffCommand(**(dict(operation_id=uuid4().hex, expected_version=inventory['member']['version'],
        kind=item['kind'], item_id=item['id'], expected_revision=item['revision'], target_user_id=recipient.user_id,
        reason='岗位交接', risk_acknowledged=True) | changes))


async def make_task(db, owner, assignee):
    thread = AgentThread(tenant_id=owner.tenant_id, user_id=owner.user_id, scene='work_task')
    db.add(thread)
    await db.flush()
    batch_row = WorkTaskBatch(batch_id='WB-'+uuid4().hex, thread_id=thread.id, tenant_id=owner.tenant_id,
        owner_id=owner.user_id, source_type='ticket', source_id='private-source', source_version='1',
        source_snapshot={'content':'private-source-secret'}, idempotency_key=uuid4().hex)
    db.add(batch_row)
    await db.flush()
    task = WorkTask(task_id='WT-'+uuid4().hex, batch_id=batch_row.id, tenant_id=owner.tenant_id,
        creator_id=owner.user_id, assignee_id=assignee.user_id, source_type='ticket', source_id='private-source',
        source_version='1', candidate_id=uuid4().hex, source_refs=['private-source-secret'], title='部门工作任务',
        priority='high', sensitive=True, due_at=datetime(2026,12,1,tzinfo=timezone.utc))
    db.add(task)
    await db.commit()
    return task.task_id


async def make_ticket(db, admin, owner):
    row = OATicket(tenant_id=admin.tenant_id,business_no='T-'+uuid4().hex,owner_id=admin.user_id,
        department_id=admin.depts[0],assignee_id=owner.user_id,category='设备',priority='medium',impact='部门',summary='private ticket details')
    db.add(row)
    await db.flush()
    return row.id


async def test_batch_is_atomic_versioned_idempotent_and_revokes_sessions(oa_db):
    from tests.integration.test_identity_sessions import configured
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        issued = await identities.issue(db, await db.get(OAUser,owner.user_id), configured())
        await db.commit()
        payload = batch([owner,recipient],status='disabled')
        result = await org.batch_update_users(db,admin,payload)
        assert all(r['status']=='disabled' and r['handoff_pending'] and r['version']==2 for r in result)
        assert await org.batch_update_users(db,admin,payload)==result
        assert await db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.actor_id==admin.user_id,AuditEvent.action=='organization.member_change'))==2
        assert (await db.scalar(select(OAAuthSession).where(OAAuthSession.user_id==owner.user_id))).revoked_at
        with pytest.raises(AppException):
            await identities.resolve_access(issued.grant.access_token,session=db,settings=configured())
        await db.rollback()
        await change(db,admin,owner.user_id,status='active')
        assert (await db.scalar(select(OAAuthSession).where(OAAuthSession.user_id==owner.user_id))).revoked_at


async def test_batch_invalid_relationship_rolls_back_prior_rows_and_audit(oa_db):
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        payload = batch([owner,recipient],manager_id=recipient.user_id)
        with pytest.raises(AppException,match='循环'):
            await org.batch_update_users(db,admin,payload)
        # Caller may keep using the transaction: no partial row or command survives.
        await db.commit()
        assert (await db.get(OAUser,owner.user_id,populate_existing=True)).authorization_version==1
        assert (await db.get(OAMembership,(admin.tenant_id,owner.user_id),populate_existing=True)).manager_id is None
        assert not await db.scalar(select(AuditEvent.id).where(AuditEvent.actor_id==admin.user_id,AuditEvent.action=='organization.member_change'))


async def test_stale_batch_cross_tenant_and_employee_are_denied(oa_db):
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        payload = batch([owner,recipient],status='disabled')
        await change(db,admin,recipient.user_id,display_name='已修改姓名')
        with pytest.raises(AppException) as stale:
            await org.batch_update_users(db,admin,payload)
        assert stale.value.http_status==409
        await db.commit()
        assert (await db.get(OAUser,owner.user_id,populate_existing=True)).status=='active'
        outsider = await seed(db,resources=['organization'])
        await db.commit()
        with pytest.raises(AppException): await org.batch_update_users(db,outsider,payload)
        await db.rollback()
        with pytest.raises(AppException): await org.batch_update_users(db,owner,payload)
        await db.rollback()
        with pytest.raises(AppException):
            await change(db,admin,owner.user_id,expected_version=99)
        await db.rollback()


async def test_last_admin_cannot_be_disabled_in_batch(oa_db):
    from tests.integration.test_identity_sessions import new_admin
    async with oa_db() as db:
        tenant, uid = await new_admin(oa_db)
        admin = await identities.current_identity(db,await db.get(OAUser,uid))
        with pytest.raises(AppException,match='管理员'):
            await org.batch_update_users(db,admin,batch([admin],status='disabled'))
        await db.commit()
        assert (await db.get(OAUser,uid,populate_existing=True)).status=='active'


async def test_transfer_department_marks_handoff_and_stales_existing_identity(oa_db):
    async with oa_db() as db:
        admin, owner, _ = await group(db)
        dept = await org.save_department(db,admin,DepartmentInput(name=uuid4().hex))
        result = await change(db,admin,owner.user_id,department_id=dept['id'])
        assert result['handoff_pending'] and result['version']==2
        with pytest.raises(AppException): await tasks.list_tasks(db,owner)
        await db.rollback()
        history = await handoffs.inventory(db,admin,owner.user_id)
        assert history['history'][0]['action']=='成员调整'


async def test_task_handoff_continues_after_creator_disabled_without_source_leak(oa_db):
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        task_id = await make_task(db,owner,owner)
        await change(db,admin,owner.user_id,status='disabled')
        inventory = await handoffs.inventory(db,admin,owner.user_id)
        assert inventory['total']==1 and inventory['counts']['work_task']==1
        item = inventory['items'][0]
        payload = transfer_command(inventory,item,recipient)
        result = await handoffs.transfer(db,admin,owner.user_id,payload)
        assert result['remaining']==0
        assert await handoffs.transfer(db,admin,owner.user_id,payload)==result
        row = await db.scalar(select(WorkTask).where(WorkTask.task_id==task_id))
        assert row.creator_id==owner.user_id and row.assignee_id==recipient.user_id
        assert row.version==row.deadline_version==2 and row.handoff_department_id==admin.depts[0]
        response = await tasks.task_command(db,recipient,task_id,WorkTaskCommand(idempotency_key='start',expected_version=2,action='start'))
        await db.commit()
        assert response.status=='IN_PROGRESS' and response.source is None and response.source_refs==[]
        response = await tasks.task_command(db,recipient,task_id,WorkTaskCommand(idempotency_key='complete',expected_version=3,action='complete'))
        await db.commit()
        assert response.status=='COMPLETED'
        assert await db.scalar(select(func.count()).select_from(WorkTaskEvent).where(WorkTaskEvent.task_id==row.id,WorkTaskEvent.action=='handoff'))==1
        finish = HandoffComplete(operation_id=uuid4().hex,expected_version=2,reason='任务已由接收人办理')
        assert not (await handoffs.complete(db,admin,owner.user_id,finish))['handoff_pending']
        assert not (await handoffs.complete(db,admin,owner.user_id,finish))['handoff_pending']


async def test_task_handoff_requires_risk_confirmation_and_rechecks_recipient(oa_db):
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        task_id = await make_task(db,owner,owner)
        inventory = await handoffs.inventory(db,admin,owner.user_id)
        item = inventory['items'][0]
        with pytest.raises(AppException,match='确认'):
            await handoffs.transfer(db,admin,owner.user_id,transfer_command(inventory,item,recipient,risk_acknowledged=False))
        await db.commit()
        assert (await db.scalar(select(WorkTask).where(WorkTask.task_id==task_id))).version==1
        await change(db,admin,recipient.user_id,status='disabled')
        with pytest.raises(AppException,match='接收人'):
            await handoffs.transfer(db,admin,owner.user_id,transfer_command(inventory,item,recipient))
        await db.commit()


async def test_hidden_other_department_tasks_still_block_signoff(oa_db):
    async with oa_db() as db:
        admin, owner, _ = await group(db)
        other_dept = await seed(db,tenant=admin.tenant_id,resources=['work_task'])
        await db.commit()
        await make_task(db,other_dept,owner)
        await change(db,admin,owner.user_id,status='disabled')
        inventory = await handoffs.inventory(db,admin,owner.user_id)
        assert inventory['total']==inventory['restricted_count']==1 and inventory['items']==[]
        assert 'private' not in str(inventory)
        with pytest.raises(AppException,match='未交接'):
            await handoffs.complete(db,admin,owner.user_id,HandoffComplete(operation_id=uuid4().hex,expected_version=2,reason='确认'))
        await db.commit()
        assert (await db.get(OAUser,owner.user_id,populate_existing=True)).handoff_pending


async def test_ticket_rules_and_direct_reports_transfer_with_history_preserved(oa_db):
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        report = await seed(db,tenant=admin.tenant_id,department=admin.depts[0],manager=owner.user_id)
        ticket_id = await make_ticket(db,admin,owner)
        rule = OATicketAssignmentRule(tenant_id=admin.tenant_id,department_id=admin.depts[0],code='device',version=1,
            category='设备',impact='*',queue='设备支持',assignee_id=owner.user_id,priority=1,enabled=True)
        db.add(rule)
        await db.commit()
        await change(db,admin,owner.user_id,status='disabled')
    for kind in ('ticket','ticket_rule','reporting_line'):
        async with oa_db() as db:
            inventory = await handoffs.inventory(db,admin,owner.user_id)
            item = next(i for i in inventory['items'] if i['kind']==kind)
            assert recipient.user_id in {u['id'] for u in await handoffs.candidates(db,admin,owner.user_id,kind,item['id'])}
            payload = transfer_command(inventory,item,recipient)
            await handoffs.transfer(db,admin,owner.user_id,payload)
            await handoffs.transfer(db,admin,owner.user_id,payload)
    async with oa_db() as db:
        assert (await handoffs.inventory(db,admin,owner.user_id))['total']==0
        ticket = await db.get(OATicket,ticket_id,populate_existing=True)
        assert ticket.assignee_id==recipient.user_id and ticket.owner_id==admin.user_id and ticket.revision==2
        rules = (await db.scalars(select(OATicketAssignmentRule).where(OATicketAssignmentRule.tenant_id==admin.tenant_id).order_by(OATicketAssignmentRule.version))).all()
        assert [r.assignee_id for r in rules]==[owner.user_id,recipient.user_id]
        membership = await db.get(OAMembership,(admin.tenant_id,report.user_id),populate_existing=True)
        assert membership.manager_id==recipient.user_id
        assert (await db.get(OAUser,report.user_id,populate_existing=True)).authorization_version==2


async def test_workflow_uses_existing_transfer_rules_and_preserves_original_seat(oa_db):
    async with oa_db() as db:
        original, recipient, _, applicant, _ = await submitted(db)
    async with oa_db() as db:
        admin = await seed(db,tenant=original.tenant_id,department=original.depts[0],resources=['organization','workflow_admin'])
        await db.commit()
        await change(db,admin,original.user_id,status='disabled')
        inventory = await handoffs.inventory(db,admin,original.user_id)
        item = next(i for i in inventory['items'] if i['kind']=='workflow')
        await handoffs.transfer(db,admin,original.user_id,transfer_command(inventory,item,recipient))
        seat = await db.get(OAWorkflowSeat,item['id'],populate_existing=True)
        assert seat.original_user_id==original.user_id and seat.effective_user_id==recipient.user_id
        assert seat.substituted
        incoming = await handoffs.inventory(db,admin,recipient.user_id)
        assert not incoming['items'][0]['can_transfer'] and incoming['items'][0]['blocked_reason']
        with pytest.raises(AppException,match='已转交'):
            await handoffs.transfer(db,admin,recipient.user_id,transfer_command(incoming,incoming['items'][0],applicant))
        await db.commit()
        context = (await approvals.list_items(db,recipient,'pending'))[0]
        result = await approvals.decide(db,recipient,context['node_id'],DecideNodeCommand(operation_id=uuid4().hex,
            expected_revision=context['revision'],action='approve'))
        await db.commit()
        assert result.result['state']=='APPROVED'


async def test_competing_task_transfers_are_serialized(oa_db):
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        task_id = await make_task(db,owner,owner)
        inventory = await handoffs.inventory(db,admin,owner.user_id)
        first = transfer_command(inventory,inventory['items'][0],recipient)
        second = transfer_command(inventory,inventory['items'][0],admin)
    async def attempt(command):
        async with oa_db() as db:
            try:
                return await handoffs.transfer(db,admin,owner.user_id,command)
            except AppException as error:
                return error.http_status
    outcomes = await asyncio.gather(attempt(first),attempt(second))
    assert sum(isinstance(r,dict) for r in outcomes)==1 and 409 in outcomes
    async with oa_db() as db:
        row = await db.scalar(select(WorkTask).where(WorkTask.task_id==task_id))
        assert row.version==2


async def test_handoff_audit_failure_rolls_back_command_and_business_change(oa_db,monkeypatch):
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        task_id = await make_task(db,owner,owner)
        inventory = await handoffs.inventory(db,admin,owner.user_id)
        def fail(*args,**kwargs): raise RuntimeError('audit unavailable')
        monkeypatch.setattr(org,'lifecycle_event',fail)
        with pytest.raises(RuntimeError):
            await handoffs.transfer(db,admin,owner.user_id,transfer_command(inventory,inventory['items'][0],recipient))
        await db.commit()
        row = await db.scalar(select(WorkTask).where(WorkTask.task_id==task_id))
        assert row.version==1 and row.assignee_id==owner.user_id


async def test_handoff_http_validates_payloads_and_enforces_organization_permission(oa_db):
    from fastapi import FastAPI
    from httpx import AsyncClient,ASGITransport
    from app.api.routers.organization import router
    from app.api.deps import get_current_user
    from app.db.session import get_db
    from fastapi.responses import JSONResponse
    app = FastAPI()
    app.include_router(router,prefix='/api')
    @app.exception_handler(AppException)
    async def error(request,exc): return JSONResponse(status_code=exc.http_status,content={'message':exc.message})
    async with oa_db() as db:
        admin, owner, _ = await group(db)
        active = [admin]
        app.dependency_overrides[get_current_user] = lambda:active[0]
        async def dependency():
            async with oa_db() as session: yield session
        app.dependency_overrides[get_db] = dependency
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.get(f'/api/organization/users/{owner.user_id}/handoff')).status_code==200
            payload = batch([owner],status='disabled').model_dump(mode='json',exclude_unset=True)
            response = await client.post('/api/organization/users/batch',json=payload)
            assert response.status_code==200, response.json()
            assert (await client.post('/api/organization/users/batch',json=payload | dict(unexpected=True))).status_code==422
            active[0] = await seed(db,tenant=admin.tenant_id,department=admin.depts[0])
            await db.commit()
            assert (await client.get(f'/api/organization/users/{owner.user_id}/handoff')).status_code==403


async def test_self_batch_and_self_signoff_are_deliberate_versioned_changes(oa_db):
    async with oa_db() as db:
        admin, _, _ = await group(db)
        result = await org.batch_update_users(db,admin,batch([admin],manager_id=None))
        assert result[0]['version']==2
    async with oa_db() as db:
        admin = await identities.current_identity(db,await db.get(OAUser,admin.user_id))
        row = await db.get(OAUser,admin.user_id)
        row.handoff_pending=True
        await db.commit()
        result = await handoffs.complete(db,admin,admin.user_id,HandoffComplete(operation_id=uuid4().hex,expected_version=2,reason='本人已确认'))
        assert not result['handoff_pending'] and result['version']==3


async def test_admin_can_handoff_own_reporting_line(oa_db):
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        await change(db,admin,admin.user_id,manager_id=owner.user_id)
    async with oa_db() as db:
        admin = await identities.current_identity(db,await db.get(OAUser,admin.user_id))
        inventory = await handoffs.inventory(db,admin,owner.user_id)
        item = next(i for i in inventory['items'] if i['kind']=='reporting_line')
        await handoffs.transfer(db,admin,owner.user_id,transfer_command(inventory,item,recipient))
    async with oa_db() as db:
        assert (await db.get(OAMembership,(admin.tenant_id,admin.user_id))).manager_id==recipient.user_id


async def test_candidates_recheck_permission_and_revision_before_transfer(oa_db):
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        task_id = await make_task(db,owner,owner)
        inventory = await handoffs.inventory(db,admin,owner.user_id)
        item = inventory['items'][0]
        assert recipient.user_id in {r['id'] for r in await handoffs.candidates(db,admin,owner.user_id,'work_task',task_id)}
        await change(db,admin,recipient.user_id,role_ids=[])
    async with oa_db() as db:
        with pytest.raises(AppException,match='接收人'):
            await handoffs.transfer(db,admin,owner.user_id,transfer_command(inventory,item,recipient))
        await db.commit()
        with pytest.raises(AppException) as error:
            await handoffs.transfer(db,admin,owner.user_id,transfer_command(inventory,item,admin,expected_revision=99))
        assert error.value.http_status==409
        await db.commit()
        row = await db.scalar(select(WorkTask).where(WorkTask.task_id==task_id))
        assert row.assignee_id==owner.user_id and row.version==1


async def test_reporting_line_candidates_prevent_cycles(oa_db):
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        report = await seed(db,tenant=admin.tenant_id,department=admin.depts[0],manager=owner.user_id)
        await db.commit()
        await change(db,admin,recipient.user_id,manager_id=report.user_id)
        inventory = await handoffs.inventory(db,admin,owner.user_id)
        item = inventory['items'][0]
        candidates = await handoffs.candidates(db,admin,owner.user_id,'reporting_line',item['id'])
        assert recipient.user_id not in {r['id'] for r in candidates} and report.user_id not in {r['id'] for r in candidates}
        with pytest.raises(AppException):
            await handoffs.transfer(db,admin,owner.user_id,transfer_command(inventory,item,recipient))
        await db.commit()


async def test_normal_completion_racing_handoff_has_one_winner(oa_db):
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        task_id = await make_task(db,owner,owner)
        inventory = await handoffs.inventory(db,admin,owner.user_id)
        await handoffs.transfer(db,admin,owner.user_id,transfer_command(inventory,inventory['items'][0],recipient))
        inventory = await handoffs.inventory(db,admin,recipient.user_id)
        payload = transfer_command(inventory,inventory['items'][0],admin)
    async def attempt(handoff):
        async with oa_db() as db:
            try:
                if handoff:
                    return await handoffs.transfer(db,admin,recipient.user_id,payload)
                result = await tasks.task_command(db,recipient,task_id,WorkTaskCommand(idempotency_key=uuid4().hex,expected_version=2,action='complete'))
                await db.commit()
                return result
            except AppException as error:
                return error.http_status
    outcomes = await asyncio.wait_for(asyncio.gather(attempt(True),attempt(False)),timeout=10)
    assert sum(not isinstance(r,int) for r in outcomes)==1
    assert any(r in (403,404,409) for r in outcomes if isinstance(r,int)), outcomes


async def test_handoff_recipient_keeps_private_overdue_reminders_without_old_source(oa_db):
    from app.services.work_task_scheduler import scan_overdue
    from app.schemas.work_task import WorkTaskCommandBase
    async with oa_db() as db:
        admin, owner, recipient = await group(db)
        task_id = await make_task(db,owner,owner)
        await change(db,admin,owner.user_id,status='disabled')
        inventory = await handoffs.inventory(db,admin,owner.user_id)
        await handoffs.transfer(db,admin,owner.user_id,transfer_command(inventory,inventory['items'][0],recipient))
    async with oa_db() as db:
        now = datetime(2026,12,3,tzinfo=timezone.utc)
        await scan_overdue(db,now)
        await db.commit()
    async with oa_db() as db:
        notices = await tasks.notifications(db,recipient)
        assert len(notices)==1 and notices[0]['task_id']==task_id and notices[0]['stage']=='overdue'
        assert 'private-source-secret' not in str(notices)
        await tasks.read_notification(db,recipient,str(notices[0]['id']),WorkTaskCommandBase(idempotency_key=uuid4().hex,expected_version=2))
        await db.commit()
        assert (await tasks.notifications(db,recipient))[0]['read_at'] is not None


@pytest.mark.parametrize('changes',[{}, {'status':None}, {'role_ids':None}, {'unknown':True}])
def test_batch_rejects_empty_or_ambiguous_changes(changes):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MemberBatch(operation_id='op',members=[dict(user_id='user',expected_version=1)],changes=changes,reason='原因')


def test_batch_rejects_duplicate_members():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MemberBatch(operation_id='op',members=[dict(user_id='user',expected_version=1)]*2,changes={'status':'disabled'},reason='原因')
