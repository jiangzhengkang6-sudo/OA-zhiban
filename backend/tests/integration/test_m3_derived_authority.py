"""Live department and reimbursement authority across derived business results."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.core.errors import AppException
from app.models.identity import OADepartment, OAMembership
from app.models.oa_workflow import OAWorkflowInstance
from app.models.work_task_notification import WorkTaskNotification
from app.schemas.document import DocumentInput, DocumentCommand, DocumentDecision
from app.schemas.email import EmailInput, EmailCommand, EmailDecision
from app.schemas.meeting import MeetingInput
from app.schemas.oa_leave import SubmitLeaveCommand
from app.schemas.oa_workflow import DecideNodeCommand
from app.schemas.report import ReportInput, ReportPlanApproval
from app.schemas.work_task import WorkTaskSourceInput, WorkTaskCommandBase, WorkTaskDraftUpdate, WorkTaskDecision
from app.services import document_service, document_generator, email_service, email_generator, meeting_service, report_service, report_query
from app.services import oa_approval_service, oa_reimbursement_service, work_task_service, work_task_scheduler
from tests.api.test_oa_reimbursement import setup as reimbursement_setup, draft, invoice
from tests.integration.test_m3_document_sources import formal_documents
from tests.integration.test_m3_formal_sources import grant, revoke, report_plan
from tests.oa_support import oa_db, seed


async def move_member(factory, actor):
    async with factory() as mutation:
        department = OADepartment(tenant_id=actor.tenant_id, name='调岗后的部门')
        mutation.add(department)
        await mutation.flush()
        await mutation.execute(update(OAMembership).where(OAMembership.tenant_id == actor.tenant_id,
            OAMembership.user_id == actor.user_id).values(department_id=department.id))
        await mutation.commit()


async def shared_record(db, scene):
    owner = await seed(db, resources=[scene])
    reader = await seed(db, tenant=owner.tenant_id, department=owner.depts[0], resources=[scene])
    await db.commit()
    if scene == 'document':
        result = await document_service.create_document(db, owner, DocumentInput(
            template_id='notice', subject='验收通知', recipient='项目组', key_points='提交验收报告',
            distribution='项目组内部', idempotency_key='department-document'))
        identifier = result.document_id
    elif scene == 'email':
        payload = EmailInput(subject='验收材料', sender='a@example.test', recipients=['b@example.test'],
            body='请提交验收报告。', idempotency_key='department-email')
        result = await email_service.create_email(db, owner, payload)
        identifier = result.email_id
    else:
        result = await meeting_service.create_meeting(db, owner, MeetingInput(
            title='验收会议', content='讨论验收材料。请提交报告。', idempotency_key='department-meeting'))
        identifier = result.meeting_id
    await db.commit()
    return owner, reader, identifier


@pytest.mark.parametrize(('scene', 'entry'), [
    (scene, entry) for scene in ('document', 'email', 'meeting')
    for entry in ('detail', 'versions', 'list') if (scene, entry) != ('meeting', 'versions')
])
async def test_formal_department_read_rechecks_owner_move(formal_documents, scene, entry):
    async with formal_documents() as db:
        owner, reader, identifier = await shared_record(db, scene)
        service = {'document': document_service, 'email': email_service, 'meeting': meeting_service}[scene]
        detail = getattr(service, 'get_' + scene)
        listing = getattr(service, 'list_' + scene + 's')
        assert await detail(db, reader, identifier)
        await move_member(formal_documents, owner)
        if entry == 'list':
            assert (await listing(db, reader)).total == 0
        else:
            with pytest.raises(AppException) as denied:
                await (detail if entry == 'detail' else service.list_versions)(db, reader, identifier)
            assert denied.value.http_status == 404


@pytest.mark.parametrize('scene', ['document', 'email', 'meeting'])
@pytest.mark.parametrize('entry', ['generate', 'retry', 'regenerate'])
@pytest.mark.parametrize('outcome', ['success', 'failure'])
async def test_formal_generation_rechecks_owner_department_after_await(formal_documents, monkeypatch, scene, entry, outcome):
    async with formal_documents() as db:
        owner, reader, identifier = await shared_record(db, scene)
        move = False
        fail = entry == 'retry'

        async def boundary():
            if move:
                await move_member(formal_documents, owner)
            if fail:
                raise RuntimeError('simulated generation outage')

        if scene == 'document':
            async def generate(payload, template, sources):
                await boundary()
                return document_generator.generate_document_draft(payload, template, sources)
            monkeypatch.setattr(document_generator, 'generate', generate)
            service, command_type, decision_type = document_service, DocumentCommand, DocumentDecision
        elif scene == 'email':
            async def generate(payload, sources):
                await boundary()
                return email_generator.generate_local(payload, sources)
            monkeypatch.setattr(email_generator, 'generate', generate)
            service, command_type, decision_type = email_service, EmailCommand, EmailDecision
        else:
            record = await meeting_service._owned(db, reader, identifier)
            refs = [str(item.id) for item in await meeting_service._segments(db, record)]
            async def generate(*args, **kwargs):
                await boundary()
                return {'draft': dict(summary='生成后的纪要', topics=[], decisions=[], action_items=[], source_refs=refs)}
            async def state(*args):
                interrupt = SimpleNamespace(id='review', value={})
                return SimpleNamespace(values={}, next=(), tasks=(SimpleNamespace(interrupts=(interrupt,)),))
            monkeypatch.setattr(meeting_service.runtime, 'invoke', generate)
            monkeypatch.setattr(meeting_service.runtime, 'resume', generate)
            monkeypatch.setattr(meeting_service.runtime, 'get_state', state)

        async def run(key, *, initial=False):
            if scene == 'meeting':
                if entry == 'regenerate' and not initial:
                    return await meeting_service.decide(db, reader, identifier, 'regenerate', None, key, expected_version=1)
                return await meeting_service.generate_draft(db, reader, identifier,
                    idempotency_key=key, retry=entry == 'retry' and not initial)
            if entry == 'regenerate' and not initial:
                return await service.decide(db, reader, identifier, decision_type(
                    idempotency_key=key, action='regenerate', expected_version=1))
            operation = service.analyze if scene == 'email' else service.generate_draft
            return await operation(db, reader, identifier, command_type(idempotency_key=key),
                retry=entry == 'retry' and not initial)

        if entry != 'generate':
            prepared = await run('prepare-generation', initial=True)
            assert prepared.status == ('PAUSED' if entry == 'retry' else 'DRAFT_READY')
            await db.commit()
        original = await getattr({'document': document_service, 'email': email_service,
            'meeting': meeting_service}[scene], 'get_' + scene)(db, reader, identifier)
        move, fail = True, outcome == 'failure'
        with pytest.raises(AppException) as denied:
            await run('shared-generation')
        assert denied.value.http_status == 404
        await db.rollback()
        restored = await getattr({'document': document_service, 'email': email_service,
            'meeting': meeting_service}[scene], 'get_' + scene)(db, owner, identifier)
        assert (restored.status, restored.version) == (original.status, original.version)


async def ended_reimbursement(db, monkeypatch):
    manager, actor, workflow = await reimbursement_setup(db)
    await grant(db, actor, 'work_task', 'report')
    identifier = await draft(db, actor, workflow)
    await invoice(db, actor, identifier, monkeypatch)
    await oa_reimbursement_service.submit(db, actor, identifier, SubmitLeaveCommand(
        operation_id='submit-derived-reimbursement', expected_revision=2, requested_submission_version=1))
    await db.commit()
    node = (await oa_approval_service.list_items(db, manager, 'pending'))[0]
    await oa_approval_service.decide(db, manager, node['node_id'], DecideNodeCommand(
        operation_id='approve-derived-reimbursement', expected_revision=node['revision'], action='approve'))
    await db.commit()
    instance = await db.scalar(select(OAWorkflowInstance).where(
        OAWorkflowInstance.tenant_id == actor.tenant_id, OAWorkflowInstance.scene == 'reimbursement'))
    assert instance.state == 'APPROVED'
    return actor, identifier, instance


@pytest.mark.parametrize('action', ['edit', 'confirm', 'reject'])
async def test_formal_meeting_review_rechecks_owner_department_after_graph(formal_documents, monkeypatch, action):
    async with formal_documents() as db:
        owner, reader, identifier = await shared_record(db, 'meeting')
        record = await meeting_service._owned(db, reader, identifier)
        refs = [str(item.id) for item in await meeting_service._segments(db, record)]
        draft = dict(summary='待确认纪要', topics=[], decisions=[], action_items=[], source_refs=refs)
        move = False

        async def graph(*args, **kwargs):
            nonlocal move
            if move:
                move = False
                await move_member(formal_documents, owner)
            return {'draft': draft}

        async def state(*args):
            interrupt = SimpleNamespace(id='review', value={})
            return SimpleNamespace(values={}, next=(), tasks=(SimpleNamespace(interrupts=(interrupt,)),))

        monkeypatch.setattr(meeting_service.runtime, 'get_state', state)
        monkeypatch.setattr(meeting_service.runtime, 'invoke', graph)
        monkeypatch.setattr(meeting_service.runtime, 'resume', graph)
        monkeypatch.setattr(meeting_service.runtime, 'update_state', graph)
        prepared = await meeting_service.generate_draft(db, reader, identifier, idempotency_key='prepare-review')
        await db.commit()
        move = True
        with pytest.raises(AppException) as denied:
            if action == 'edit':
                await meeting_service.save_draft(db, reader, identifier, {**draft, 'summary': '修改后的纪要'},
                    idempotency_key='moved-review', expected_version=1)
            else:
                await meeting_service.decide(db, reader, identifier, action, '人工意见', 'moved-review', expected_version=1)
        assert denied.value.http_status == 404
        await db.rollback()
        restored = await meeting_service.get_meeting(db, owner, identifier)
        assert (restored.status, restored.version, restored.draft) == (prepared.status, prepared.version, prepared.draft)


async def reimbursement_task(db, actor, identifier, *, assignee_id=None):
    batch = await work_task_service.create_batch(db, actor, WorkTaskSourceInput(
        source_type='approval', source_id=identifier, source_version=1, idempotency_key='reimbursement-batch'))
    batch = await work_task_service.extract(db, actor, batch.batch_id, WorkTaskCommandBase(
        idempotency_key='extract-reimbursement', expected_version=0))
    candidate = batch.draft.candidates[0].model_dump(mode='json')
    candidate.update(assignee_id=assignee_id or actor.user_id, due_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    batch = await work_task_service.save_draft(db, actor, batch.batch_id, WorkTaskDraftUpdate(
        idempotency_key='save-reimbursement-task', expected_version=1, draft={'candidates': [candidate]}))
    batch = await work_task_service.decide(db, actor, batch.batch_id, WorkTaskDecision(
        action='confirm', idempotency_key='confirm-reimbursement-task', expected_version=2,
        selected_candidate_ids=[candidate['candidate_id']], metadata_confirmed=True))
    await db.commit()
    return batch


async def test_reimbursement_task_and_report_share_formal_version_and_revoke_live(formal_documents, monkeypatch):
    async with formal_documents() as db:
        actor, identifier, instance = await ended_reimbursement(db, monkeypatch)
        batch = await reimbursement_task(db, actor, identifier)
        assert batch.source['version'] == '1' and 'APPROVED' in batch.source['content']
        plan = report_plan('approval_outcomes')
        snapshot = await report_query.execute_plan(actor, plan)
        assert snapshot['metrics'][0]['source_ids'] == [instance.id]
        assert snapshot['metrics'][0]['status_counts'] == {'APPROVED': 1}
        task_snapshot = await report_query.execute_plan(actor, report_plan('work_task_progress'))
        assert task_snapshot['metrics'][0]['current'] == 1
        await revoke(db, actor, 'reimbursement')
        with pytest.raises(AppException) as denied:
            await work_task_service.get_batch(db, actor, batch.batch_id)
        assert denied.value.http_status == 403
        assert (await report_query.execute_plan(actor, report_plan('work_task_progress')))['metrics'][0]['current'] == 0
        with pytest.raises(AppException):
            await report_query.validate_snapshot_scope(db, actor, report_plan('work_task_progress'), task_snapshot)


async def test_reimbursement_background_scan_stops_when_source_permission_is_revoked(formal_documents, monkeypatch):
    async with formal_documents() as db:
        actor, identifier, _ = await ended_reimbursement(db, monkeypatch)
        await reimbursement_task(db, actor, identifier)
        await revoke(db, actor, 'reimbursement')
        await work_task_scheduler.scan_overdue(db)
        await db.commit()
        assert (await db.scalars(select(WorkTaskNotification).where(
            WorkTaskNotification.tenant_id == actor.tenant_id))).all() == []


@pytest.mark.parametrize('change', ['recipient_disabled', 'creator_disabled', 'source_owner_moved'])
async def test_background_task_reminders_recheck_live_people_and_source(formal_documents, monkeypatch, change):
    from app.models.identity import OAUser
    async with formal_documents() as db:
        actor, identifier, _ = await ended_reimbursement(db, monkeypatch)
        recipient = await seed(db, tenant=actor.tenant_id, department=actor.depts[0],
            resources=['work_task', 'reimbursement'])
        await db.commit()
        await reimbursement_task(db, actor, identifier, assignee_id=recipient.user_id)
    if change == 'source_owner_moved':
        await move_member(formal_documents, actor)
    else:
        user_id = recipient.user_id if change == 'recipient_disabled' else actor.user_id
        async with formal_documents() as mutation:
            await mutation.execute(update(OAUser).where(OAUser.id == user_id).values(status='disabled'))
            await mutation.commit()
    async with formal_documents() as db:
        await work_task_scheduler.scan_overdue(db)
        await db.commit()
        reminders = (await db.scalars(select(WorkTaskNotification).where(
            WorkTaskNotification.tenant_id == actor.tenant_id))).all()
        assert not any(row.recipient_id == recipient.user_id for row in reminders)
        if change == 'creator_disabled':
            assert reminders == []
        else:
            assert [(row.recipient_id, row.stage) for row in reminders] == [(actor.user_id, 'escalated')]


async def test_builtin_scheduler_reminds_existing_tasks_when_ai_is_disabled(formal_documents, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from app.core import config
    from app.services import scheduler, oa_workflow_scheduler, oa_notification_service, oa_notification_worker
    async with formal_documents() as db:
        actor, identifier, _ = await ended_reimbursement(db, monkeypatch)
        await reimbursement_task(db, actor, identifier)
    stop = asyncio.Event()
    original_scan = work_task_scheduler.scan_overdue

    async def scan_and_stop(db):
        result = await original_scan(db)
        stop.set()
        return result

    monkeypatch.setattr(config.get_settings(), 'ai_enabled', False)
    monkeypatch.setattr(scheduler, 'async_session_factory', formal_documents)
    monkeypatch.setattr(oa_workflow_scheduler, 'scan', AsyncMock(return_value={'errors': []}))
    monkeypatch.setattr(oa_notification_service, 'dispatch', AsyncMock())
    monkeypatch.setattr(oa_notification_worker, 'run_once', AsyncMock())
    monkeypatch.setattr(work_task_scheduler, 'scan_overdue', scan_and_stop)
    # Bound the regression failure: the old loop never invokes scan_and_stop.
    try:
        await asyncio.wait_for(scheduler.run_scheduler(stop), timeout=2)
    except TimeoutError:
        pytest.fail('builtin scheduler did not scan existing work tasks with AI disabled')
    async with formal_documents() as db:
        reminders = (await db.scalars(select(WorkTaskNotification).where(
            WorkTaskNotification.tenant_id == actor.tenant_id))).all()
        assert {row.stage for row in reminders} == {'overdue', 'escalated'}
        assert {row.recipient_id for row in reminders} == {actor.user_id}
        await original_scan(db)
        assert len((await db.scalars(select(WorkTaskNotification).where(
            WorkTaskNotification.tenant_id == actor.tenant_id))).all()) == 2


@pytest.mark.parametrize('entry', ['detail', 'versions', 'create_replay', 'approve_replay'])
async def test_reimbursement_report_cached_results_recheck_source_permission(formal_documents, monkeypatch, entry):
    async with formal_documents() as db:
        actor, _, _ = await ended_reimbursement(db, monkeypatch)
        payload = ReportInput(subject='正式报销审批统计', plan=report_plan('approval_outcomes'), idempotency_key='formal-report')
        created = await report_service.create_report(db, actor, payload)
        command = ReportPlanApproval(idempotency_key='approve-report', expected_version=1, plan_confirmed=True)
        generated = await report_service.approve_plan(db, actor, created.report_id, command)
        assert generated.status == 'DRAFT_READY'
        assert generated.snapshot['metrics'][0]['current'] == 1
        await db.commit()
        await revoke(db, actor, 'reimbursement')
        with pytest.raises(AppException) as denied:
            if entry == 'detail':
                await report_service.get_report(db, actor, created.report_id)
            elif entry == 'versions':
                await report_service.list_versions(db, actor, created.report_id)
            elif entry == 'create_replay':
                await report_service.create_report(db, actor, payload)
            else:
                await report_service.approve_plan(db, actor, created.report_id, command)
        assert denied.value.http_status == 403
