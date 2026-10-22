"""Real formal sources, cached derivatives and live authority in the M3 test DB."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.core.errors import AppException
from app.models.identity import OAPermission, OARolePermission, OAUserRole, OAMembership
from app.models.oa_workflow import OAWorkflowInstance
from app.schemas.oa_leave import SubmitLeaveCommand
from app.schemas.oa_workflow import DecideNodeCommand
from app.schemas.report import ReportPlan
from app.schemas.work_task import WorkTaskSourceInput
from app.services import identity_service, work_task_service, report_query
from app.services import oa_approval_service as approvals, oa_leave_service as leaves
from tests.api.test_oa_ticket import setup, create
from tests.contracts.test_builtin_leave_gateway import draft_fixture
from tests.oa_support import oa_db, seed


async def grant(db, actor, *resources):
    role_id = await db.scalar(select(OAUserRole.role_id).where(OAUserRole.tenant_id == actor.tenant_id,
        OAUserRole.user_id == actor.user_id))
    for resource in resources:
        for action in ('read', 'write'):
            permission = await db.scalar(select(OAPermission).where(OAPermission.resource == resource,
                OAPermission.action == action, OAPermission.scope == 'self'))
            if permission is None:
                permission = OAPermission(resource=resource, action=action, scope='self')
                db.add(permission)
                await db.flush()
            db.add(OARolePermission(tenant_id=actor.tenant_id, role_id=role_id, permission_id=permission.id))
    await db.commit()


async def revoke(db, actor, resource):
    await db.execute(delete(OARolePermission).where(OARolePermission.tenant_id == actor.tenant_id,
        OARolePermission.role_id.in_(select(OAUserRole.role_id).where(OAUserRole.user_id == actor.user_id)),
        OARolePermission.permission_id.in_(select(OAPermission.id).where(OAPermission.resource == resource))))
    await db.commit()


def report_plan(metric):
    today = datetime.now().date()
    return ReportPlan(metrics=[metric], start=today.isoformat(), end=(today + timedelta(days=1)).isoformat())


async def ended_leave(db):
    manager, actor, _, draft = await draft_fixture(db)
    await grant(db, actor, 'work_task', 'report')
    await grant(db, manager, 'work_task')
    await leaves.submit(db, actor, draft['id'], SubmitLeaveCommand(
        operation_id='submit-source', expected_revision=1, requested_submission_version=1))
    await db.commit()
    item = (await approvals.list_items(db, manager, 'pending'))[0]
    await approvals.decide(db, manager, item['node_id'], DecideNodeCommand(operation_id='approve-source',
        expected_revision=item['revision'], action='approve'))
    await db.commit()
    instance = await db.scalar(select(OAWorkflowInstance).where(OAWorkflowInstance.tenant_id == actor.tenant_id))
    assert instance.state == 'APPROVED'
    return manager, actor, draft, instance


async def test_formal_ticket_task_source_and_persisted_batch_revoke_live_authority(oa_db):
    async with oa_db() as db:
        _, actor = await setup(db)
        await grant(db, actor, 'work_task', 'report')
        ticket, _, _ = await create(db, actor)
        source = await work_task_service.load_source(db, actor, 'ticket', ticket['business_no'])
        assert source['version'] == str(ticket['revision'])
        assert ticket['summary'] in source['content']
        assert source['ref'] == f"ticket:{ticket['business_no']}:1"
        batch = await work_task_service.create_batch(db, actor, WorkTaskSourceInput(
            source_type='ticket', source_id=ticket['id'], idempotency_key='formal-batch'))
        await db.commit()
        assert (await work_task_service.get_batch(db, actor, batch.batch_id)).source == batch.source
        with pytest.raises(AppException) as stale:
            await work_task_service.load_source(db, actor, 'ticket', ticket['id'], source_version=2)
        assert stale.value.http_status == 409
        await revoke(db, actor, 'ticket')
        with pytest.raises(AppException) as revoked:
            await work_task_service.get_batch(db, actor, batch.batch_id)
        assert revoked.value.http_status == 403
        assert await work_task_service.list_batches(db, actor) == []


async def test_formal_approval_sources_are_terminal_versioned_and_currently_scoped(oa_db):
    async with oa_db() as db:
        manager, actor, draft, instance = await ended_leave(db)
        for reader, identifier in [(actor, draft['business_no']), (manager, instance.id)]:
            source = await work_task_service.load_source(db, reader, 'approval', identifier, source_version=1)
            assert source['version'] == '1'
            assert 'APPROVED' in source['content']
        outsider = await seed(db, tenant=actor.tenant_id, resources=['work_task', 'approval'], scope='self')
        await db.commit()
        with pytest.raises(AppException) as denied:
            await work_task_service.load_source(db, outsider, 'approval', instance.id)
        assert denied.value.http_status in {403, 404}
        await revoke(db, actor, 'leave')
        with pytest.raises(AppException) as revoked:
            await work_task_service.load_source(db, actor, 'approval', draft['id'])
        assert revoked.value.http_status == 403


async def test_formal_approval_source_denies_pending_workflow(oa_db):
    async with oa_db() as db:
        _, actor, _, draft = await draft_fixture(db)
        await grant(db, actor, 'work_task')
        await leaves.submit(db, actor, draft['id'], SubmitLeaveCommand(
            operation_id='pending-source', expected_revision=1, requested_submission_version=1))
        await db.commit()
        with pytest.raises(AppException) as pending:
            await work_task_service.load_source(db, actor, 'approval', draft['id'])
        assert pending.value.http_status == 422


async def test_formal_report_counts_only_current_owners_and_revokes_cached_sources(oa_db):
    async with oa_db() as db:
        _, actor = await setup(db)
        await grant(db, actor, 'report')
        ticket, _, _ = await create(db, actor)
        other = await seed(db, tenant=actor.tenant_id, department=actor.depts[0], resources=['ticket'], scope='self')
        await db.commit()
        await create(db, other, key='other-ticket')
        plan = report_plan('ticket_volume')
        snapshot = await report_query.execute_plan(actor, plan)
        metric = snapshot['metrics'][0]
        assert metric['current'] == 1
        assert metric['source'] == 'oa_ticket'
        assert metric['source_ids'] == [ticket['id']]
        await report_query.validate_snapshot_scope(db, actor, plan, snapshot)
        await revoke(db, actor, 'ticket')
        with pytest.raises(AppException) as revoked:
            await report_query.validate_snapshot_scope(db, actor, plan, snapshot)
        assert revoked.value.http_status == 403
        with pytest.raises(AppException):
            await report_query.execute_plan(actor, plan)


async def test_formal_report_approval_counts_typed_instances_and_denies_empty_cache_after_revoke(oa_db):
    async with oa_db() as db:
        _, actor, _, instance = await ended_leave(db)
        plan = report_plan('approval_outcomes')
        snapshot = await report_query.execute_plan(actor, plan)
        metric = snapshot['metrics'][0]
        assert metric['source'] == 'oa_workflow_instance'
        assert metric['current'] == 1 and metric['status_counts'] == {'APPROVED': 1}
        assert metric['source_ids'] == [instance.id]
        await revoke(db, actor, 'leave')
        with pytest.raises(AppException):
            await report_query.validate_snapshot_scope(db, actor, plan, None)


async def test_formal_tenant_report_does_not_use_role_names_as_authority(oa_db):
    actor = type('Actor', (), {'data_scope': {'identity_provider': 'builtin', 'all': True},
        'roles': ['admin'], 'tenant_id': 'test', 'user_id': 'test', 'depts': []})()
    with pytest.raises(AppException) as error:
        report_query.scope_fingerprint(actor, 'tenant')
    assert error.value.http_status == 403
