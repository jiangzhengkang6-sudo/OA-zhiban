"""Formal applicant confirmation uses domain drafts and durable decisions."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.core import config
from app.core.context import get_current_user, set_current_user
from app.core.errors import AppException
from app.graph.graph_service import GraphRuntime
from app.graph.nodes import common
from app.models.agent_thread import AgentThread
from app.models.human_decision import HumanDecision
from app.models.oa_bridge import OABridgeConfirmation
from app.models.oa_leave import OALeave, OALeaveVersion
from app.models.oa_workflow import OAWorkflowOperation
from app.providers import identity
from app.schemas.oa_leave import LeaveDraftPatch
from app.services import interrupt_service, policy_service, thread_service, oa_leave_service as leaves
from tests.contracts.test_builtin_leave_gateway import draft_fixture
from tests.m3_http_support import authenticated_client
from tests.oa_support import oa_db, seed


@pytest.fixture
async def leave_runtime(oa_db, monkeypatch):
    settings = policy_service.get_settings()
    monkeypatch.setattr(settings, 'oa_provider', 'builtin')
    monkeypatch.setattr(settings, 'auth_provider', 'builtin')
    monkeypatch.setattr(config, 'get_settings', lambda: settings)
    monkeypatch.setattr(identity, 'get_settings', lambda: settings)
    for module in (common, interrupt_service):
        monkeypatch.setattr(module, 'async_session_factory', oa_db)
    # The formal graph must use the same approved factory as the other nodes.
    from app.db import session
    monkeypatch.setattr(session, 'async_session_factory', oa_db)
    monkeypatch.setattr(common, 'get_adapter', lambda: pytest.fail('formal leave called legacy adapter'))
    monkeypatch.setattr(thread_service, 'get_adapter', lambda: pytest.fail('formal leave called legacy adapter'))
    previous = get_current_user()
    runtime = GraphRuntime()
    await runtime.initialize()
    monkeypatch.setattr(thread_service, 'runtime', runtime)
    monkeypatch.setattr(interrupt_service, 'runtime', runtime)
    try:
        yield oa_db, runtime
    finally:
        await runtime.close()
        set_current_user(previous)


async def applicant(factory):
    from app.models.identity import OAUserRole, OARolePermission, OAPermission
    async with factory() as db:
        admin, actor, _, draft = await draft_fixture(db)
        role_id = await db.scalar(select(OAUserRole.role_id).where(OAUserRole.user_id == actor.user_id))
        for action in ('read', 'write'):
            permission = await db.scalar(select(OAPermission).where(OAPermission.resource == 'thread',
                OAPermission.action == action, OAPermission.scope == 'self'))
            if permission is None:
                permission = OAPermission(resource='thread', action=action, scope='self')
                db.add(permission)
                await db.flush()
            db.add(OARolePermission(tenant_id=actor.tenant_id, role_id=role_id, permission_id=permission.id))
        await db.commit()
        return admin, actor, draft


async def open_leave(client, draft):
    created = await client.post('/api/agent/threads', json={'scene': 'leave', 'business_id': draft['id']})
    assert created.status_code == 200, created.text
    identifier = created.json()['data']['thread_id']
    url = '/api/agent/threads/' + identifier
    response = await client.post(url + '/messages', json={'content': '请核对并提交这份请假申请', 'idempotency_key': 'review'})
    assert response.status_code == 200, response.text
    detail = await client.get(url)
    assert detail.status_code == 200, detail.text
    data = detail.json()['data']
    assert data['current_interrupt_id'] and data['form_snapshot']['reason']
    return identifier, url, data


async def version_count(factory, actor):
    async with factory() as db:
        return await db.scalar(select(func.count()).select_from(OALeaveVersion).where(OALeaveVersion.tenant_id == actor.tenant_id))


async def test_formal_leave_confirm_restart_and_repeat(leave_runtime, monkeypatch):
    factory, first = leave_runtime
    _, actor, draft = await applicant(factory)
    second = GraphRuntime()
    try:
        async with authenticated_client(factory, monkeypatch, actor) as client:
            identifier, url, data = await open_leave(client, draft)
            assert await version_count(factory, actor) == 0
            await first.close()
            await second.initialize()
            monkeypatch.setattr(thread_service, 'runtime', second)
            monkeypatch.setattr(interrupt_service, 'runtime', second)
            endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
            request = {'action': 'confirm', 'idempotency_key': 'submit-once'}
            response = await client.post(endpoint, json=request)
            assert response.status_code == 200, response.text
            assert (await client.post(endpoint, json=request)).status_code == 200
            assert (await client.post(endpoint, json={**request, 'comment': 'changed'})).status_code == 409
            current = (await client.get(url)).json()['data']
            assert current['approval_status'] == 'IN_REVIEW'
            assert current['current_interrupt_id'] is None
            assert await version_count(factory, actor) == 1
            async with factory() as db:
                bindings = (await db.scalars(select(OABridgeConfirmation).where(OABridgeConfirmation.thread_id == identifier))).all()
                assert len(bindings) == 1 and bindings[0].consumed_operation_id
    finally:
        await second.close()


async def test_formal_leave_stale_draft_is_not_submitted(leave_runtime, monkeypatch):
    factory, _ = leave_runtime
    _, actor, draft = await applicant(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, _, data = await open_leave(client, draft)
        async with factory() as db:
            await leaves.update_draft(db, actor, draft['id'], LeaveDraftPatch(operation_id='external-edit',
                expected_revision=1, fields={**draft['fields'], 'reason': '已在工作台修改'}))
            await db.commit()
        response = await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume',
            json={'action': 'confirm', 'idempotency_key': 'stale'})
        assert response.status_code == 409, response.text
        assert await version_count(factory, actor) == 0


@pytest.mark.parametrize('action', ['confirm', 'cancel'])
async def test_formal_leave_recovery_replays_saved_decision(leave_runtime, monkeypatch, action):
    factory, runtime = leave_runtime
    _, actor, draft = await applicant(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_leave(client, draft)
        endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        assert (await client.post(endpoint, json={'action': 'reconcile'})).status_code == 409
        original = runtime.resume
        monkeypatch.setattr(runtime, 'resume', AsyncMock(side_effect=RuntimeError('checkpoint unavailable')))
        response = await client.post(endpoint, json={'action': action, 'idempotency_key': 'original-key'})
        assert response.status_code == 200, response.text
        assert (await client.get(url)).json()['data']['error']['code'] == 'GRAPH_RECOVERY'
        monkeypatch.setattr(runtime, 'resume', original)
        assert (await client.post(endpoint, json={'action': 'reconcile', 'edited_data': {'reason': 'forged'}})).status_code == 422
        recovered = await client.post(endpoint, json={'action': 'reconcile'})
        assert recovered.status_code == 200, recovered.text
        assert (await client.get(url)).json()['data']['error'] is None
        assert await version_count(factory, actor) == (1 if action == 'confirm' else 0)


@pytest.mark.parametrize('change', ['permission', 'policy', 'tools'])
async def test_formal_leave_confirm_rechecks_authority(leave_runtime, monkeypatch, change):
    factory, _ = leave_runtime
    _, actor, draft = await applicant(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, _, data = await open_leave(client, draft)
        async with factory() as db:
            if change == 'permission':
                from tests.integration.test_m3_formal_sources import revoke
                await revoke(db, actor, 'leave')
            else:
                from app.services.oa_scope_service import upsert_formal_policy
                await upsert_formal_policy(db, actor=actor, scene='leave', scope_type='tenant', scope_value=None,
                    enabled=change != 'policy', thresholds={'allowed_tools': ['get_user_context']} if change == 'tools' else {},
                    rule_version='test')
                await db.commit()
        response = await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume',
            json={'action': 'confirm', 'idempotency_key': 'denied'})
        assert response.status_code in {401, 403, 503}, response.text
        assert await version_count(factory, actor) == 0


async def test_formal_leave_concurrent_confirmation_is_single_write(leave_runtime, monkeypatch):
    factory, _ = leave_runtime
    _, actor, draft = await applicant(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        identifier, url, data = await open_leave(client, draft)
        endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        request = {'action': 'confirm', 'idempotency_key': 'concurrent'}
        results = await asyncio.gather(client.post(endpoint, json=request), client.post(endpoint, json=request))
        assert all(result.status_code == 200 for result in results), [result.text for result in results]
        assert await version_count(factory, actor) == 1
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(HumanDecision).where(HumanDecision.thread_id == UUID(identifier))) == 1
            assert await db.scalar(select(func.count()).select_from(OAWorkflowOperation).where(
                OAWorkflowOperation.tenant_id == actor.tenant_id, OAWorkflowOperation.kind == 'leave.submit')) == 1


async def test_formal_leave_other_owner_cannot_read_or_confirm(leave_runtime, monkeypatch):
    factory, _ = leave_runtime
    _, actor, draft = await applicant(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_leave(client, draft)
    async with factory() as db:
        stranger = await seed(db, tenant=actor.tenant_id, department=actor.depts[0], resources=['thread', 'leave'])
        await db.commit()
    async with authenticated_client(factory, monkeypatch, stranger) as client:
        assert (await client.get(url)).status_code == 403
        assert (await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume',
            json={'action': 'confirm'})).status_code == 403
    assert await version_count(factory, actor) == 0


async def test_formal_leave_edit_refreshes_expired_review_after_workbench_edit(leave_runtime, monkeypatch):
    factory, _ = leave_runtime
    _, actor, draft = await applicant(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        identifier, url, data = await open_leave(client, draft)
        async with factory() as db:
            binding = await db.scalar(select(OABridgeConfirmation).where(OABridgeConfirmation.thread_id == identifier))
            binding.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        assert (await client.post(endpoint, json={'action': 'confirm'})).status_code == 422
        async with factory() as db:
            await leaves.update_draft(db, actor, draft['id'], LeaveDraftPatch(operation_id='workbench-edit',
                expected_revision=1, fields={**draft['fields'], 'reason': '最新事由'}))
            await db.commit()
        refreshed = await client.post(endpoint, json={'action': 'edit', 'idempotency_key': 'refresh'})
        assert refreshed.status_code == 200, refreshed.text
        current = (await client.get(url)).json()['data']
        assert current['form_snapshot']['reason'] == '最新事由'
        assert current['current_interrupt_id'] != data['current_interrupt_id']
        assert (await client.post('/api/agent/interrupts/' + current['current_interrupt_id'] + '/resume',
            json={'action': 'confirm'})).status_code == 200
        assert await version_count(factory, actor) == 1


async def test_formal_leave_decision_audit_failure_rolls_back_domain_and_binding(leave_runtime, monkeypatch):
    from app.services import audit_service
    factory, _ = leave_runtime
    _, actor, draft = await applicant(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        identifier, _, data = await open_leave(client, draft)
        original = audit_service.audit
        async def fail_decision(db, action, **kwargs):
            if action == 'human_decided':
                raise RuntimeError('decision audit unavailable')
            return await original(db, action, **kwargs)
        monkeypatch.setattr(audit_service, 'audit', fail_decision)
        with pytest.raises(RuntimeError, match='decision audit unavailable'):
            await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume', json={'action': 'confirm'})
        assert await version_count(factory, actor) == 0
        async with factory() as db:
            binding = await db.scalar(select(OABridgeConfirmation).where(OABridgeConfirmation.thread_id == identifier))
            assert binding.consumed_operation_id is None
            assert await db.scalar(select(func.count()).select_from(HumanDecision).where(HumanDecision.thread_id == UUID(identifier))) == 0
            assert await db.scalar(select(func.count()).select_from(OAWorkflowOperation).where(
                OAWorkflowOperation.tenant_id == actor.tenant_id, OAWorkflowOperation.kind == 'leave.submit')) == 0
            assert (await db.get(OALeave, draft['id'])).state == 'DRAFT'


async def test_formal_leave_recovery_checks_domain_result_after_graph_already_finished(leave_runtime, monkeypatch):
    from app.adapters.builtin_gateway import BuiltinGateway
    factory, runtime = leave_runtime
    _, actor, draft = await applicant(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_leave(client, draft)
        original = runtime.resume
        async def finish_then_disconnect(*args, **kwargs):
            await original(*args, **kwargs)
            raise RuntimeError('response lost after checkpoint committed')
        monkeypatch.setattr(runtime, 'resume', finish_then_disconnect)
        endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        assert (await client.post(endpoint, json={'action': 'confirm'})).status_code == 200
        assert (await client.get(url)).json()['data']['error']['code'] == 'GRAPH_RECOVERY'
        monkeypatch.setattr(runtime, 'resume', original)
        result = BuiltinGateway.get_approval_result
        monkeypatch.setattr(BuiltinGateway, 'get_approval_result', AsyncMock(return_value=None))
        response = await client.post(endpoint, json={'action': 'reconcile'})
        assert response.status_code == 409, response.text
        monkeypatch.setattr(BuiltinGateway, 'get_approval_result', result)
        assert (await client.post(endpoint, json={'action': 'reconcile'})).status_code == 200
        assert (await client.get(url)).json()['data']['error'] is None
        assert await version_count(factory, actor) == 1


async def test_formal_leave_workflow_change_requires_new_review(leave_runtime, monkeypatch):
    from app.schemas.oa_workflow import WorkflowSave, PublishWorkflow
    from app.services import oa_workflow_service as workflows
    from tests.unit.test_oa_workflow_definition import definition
    factory, _ = leave_runtime
    admin, actor, draft = await applicant(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, _, data = await open_leave(client, draft)
        async with factory() as db:
            package = definition()
            package['rules']['timeout_hours'] = 72
            updated = await workflows.save_definition(db, admin, WorkflowSave(operation_id='new-route',
                expected_revision=2, department_id=actor.depts[0], code='leave', name='请假', definition=package),
                definition_id=draft['workflow_definition_id'])
            await workflows.publish_definition(db, admin, updated['id'], PublishWorkflow(operation_id='publish-route', expected_revision=3))
            await db.commit()
        response = await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume', json={'action': 'confirm'})
        assert response.status_code == 409, response.text
        assert await version_count(factory, actor) == 0


@pytest.mark.parametrize('changed_field', ['confirmation_id', 'review_route_hash'])
async def test_formal_leave_forged_checkpoint_cannot_authorize_write(leave_runtime, monkeypatch, changed_field):
    from types import SimpleNamespace
    from uuid import uuid4
    from app.graph.graph_service import extract_interrupt
    factory, runtime = leave_runtime
    _, actor, draft = await applicant(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        identifier, _, data = await open_leave(client, draft)
        original = runtime.get_state
        interrupt_id, pending = extract_interrupt(await original(identifier))
        forged = {**pending, 'form_snapshot': dict(pending['form_snapshot'])}
        if changed_field == 'confirmation_id':
            forged['confirmation_id'] = str(uuid4())
        else:
            forged['form_snapshot']['review_route_hash'] = '0' * 64
        monkeypatch.setattr(runtime, 'get_state', AsyncMock(return_value=SimpleNamespace(tasks=[
            SimpleNamespace(interrupts=[SimpleNamespace(id=interrupt_id, value=forged)])])))
        endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        response = await client.post(endpoint, json={'action': 'confirm'})
        expected_status = 409 if changed_field == 'confirmation_id' else 422
        assert response.status_code == expected_status, response.text
        assert await version_count(factory, actor) == 0
        async with factory() as db:
            binding = await db.scalar(select(OABridgeConfirmation).where(OABridgeConfirmation.thread_id == identifier))
            assert binding.consumed_operation_id is None
            assert await db.scalar(select(func.count()).select_from(HumanDecision).where(
                HumanDecision.thread_id == UUID(identifier))) == 0
        monkeypatch.setattr(runtime, 'get_state', original)
        assert (await client.post(endpoint, json={'action': 'confirm'})).status_code == 200
        assert await version_count(factory, actor) == 1


async def test_formal_leave_manager_change_requires_new_review(leave_runtime, monkeypatch):
    from app.models.identity import OAMembership
    factory, _ = leave_runtime
    _, actor, draft = await applicant(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_leave(client, draft)
        async with factory() as db:
            replacement = await seed(db, tenant=actor.tenant_id, department=actor.depts[0], resources=['approval'])
            membership = await db.scalar(select(OAMembership).where(OAMembership.user_id == actor.user_id,
                OAMembership.tenant_id == actor.tenant_id))
            membership.manager_id = replacement.user_id
            await db.commit()
        endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        response = await client.post(endpoint, json={'action': 'confirm'})
        assert response.status_code == 409, response.text
        assert await version_count(factory, actor) == 0
        assert (await client.post(endpoint, json={'action': 'edit'})).status_code == 200
        current = (await client.get(url)).json()['data']
        assert current['current_interrupt_id'] != data['current_interrupt_id']
        response = await client.post('/api/agent/interrupts/' + current['current_interrupt_id'] + '/resume',
            json={'action': 'confirm'})
        assert response.status_code == 200, response.text
        assert await version_count(factory, actor) == 1


@pytest.mark.parametrize('change', ['permission', 'policy', 'tools'])
async def test_formal_leave_recovery_rechecks_authority_after_commit(leave_runtime, monkeypatch, change):
    factory, runtime = leave_runtime
    _, actor, draft = await applicant(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        identifier, url, data = await open_leave(client, draft)
        original = runtime.resume
        monkeypatch.setattr(runtime, 'resume', AsyncMock(side_effect=RuntimeError('checkpoint unavailable')))
        endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        assert (await client.post(endpoint, json={'action': 'confirm'})).status_code == 200
        assert (await client.get(url)).json()['data']['error']['code'] == 'GRAPH_RECOVERY'
        monkeypatch.setattr(runtime, 'resume', original)
        async with factory() as db:
            if change == 'permission':
                from tests.integration.test_m3_formal_sources import revoke
                await revoke(db, actor, 'leave')
            else:
                from app.services.oa_scope_service import upsert_formal_policy
                await upsert_formal_policy(db, actor=actor, scene='leave', scope_type='tenant', scope_value=None,
                    enabled=change != 'policy', thresholds={'allowed_tools': ['get_user_context']} if change == 'tools' else {},
                    rule_version='test')
                await db.commit()
        response = await client.post(endpoint, json={'action': 'reconcile'})
        assert response.status_code in {401, 403, 503}, response.text
        if change == 'policy':
            assert (await client.get(url)).status_code == 503
            # Disabling AI must leave the canonical manual business record readable.
            manual = await client.get('/api/oa/leaves/' + draft['id'])
            assert manual.status_code == 200, manual.text
            assert manual.json()['data']['state'] == 'IN_REVIEW'
        assert await version_count(factory, actor) == 1
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(HumanDecision).where(
                HumanDecision.thread_id == UUID(identifier))) == 1
            assert (await db.get(AgentThread, UUID(identifier))).error_code == 'GRAPH_RECOVERY'
