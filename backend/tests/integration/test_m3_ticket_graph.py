"""Formal ticket graph authority, human confirmation and durable recovery."""
import asyncio
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.core import config
from app.core.context import get_current_user, set_current_user
from app.core.errors import AppException
from app.graph.graph_service import GraphRuntime
from app.graph.nodes import common, ticket_nodes
from app.models.oa_ticket import OATicket
from app.models.ticket_record import TicketRecord
from app.models.oa_bridge import OABridgeConfirmation
from app.models.human_decision import HumanDecision
from app.models.oa_ai_scope import OABusinessAudit
from app.models.oa_workflow import OAWorkflowOperation, OAWorkflowEvent
from app.services import thread_service, interrupt_service, policy_service
from app.providers import identity
from tests.oa_support import oa_db, seed
from tests.m3_http_support import authenticated_client


@pytest.fixture
async def ticket_runtime(oa_db, monkeypatch):
    settings = policy_service.get_settings()
    monkeypatch.setattr(settings, 'oa_provider', 'builtin')
    monkeypatch.setattr(settings, 'auth_provider', 'builtin')
    monkeypatch.setattr(config, 'get_settings', lambda: settings)
    monkeypatch.setattr(identity, 'get_settings', lambda: settings)
    for module in (common, ticket_nodes, interrupt_service):
        monkeypatch.setattr(module, 'async_session_factory', oa_db)
    monkeypatch.setattr(common, 'get_adapter', lambda: pytest.fail('formal graph called legacy adapter'))
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


async def owner(factory):
    async with factory() as db:
        actor = await seed(db, resources=['thread', 'ticket'])
        await db.commit()
        return actor


async def open_ticket(client):
    created = await client.post('/api/agent/threads', json={'scene': 'ticket'})
    assert created.status_code == 200, created.text
    identifier = created.json()['data']['thread_id']
    url = '/api/agent/threads/' + identifier
    sent = await client.post(url + '/messages', json={'content': '电脑无法启动，需要维修', 'idempotency_key': 'describe'})
    assert sent.status_code == 200, sent.text
    detail = await client.get(url)
    assert detail.status_code == 200, detail.text
    data = detail.json()['data']
    assert data['current_interrupt_id'] and data['ticket_fields']['summary']
    return identifier, url, data


async def count_tickets(factory, actor):
    async with factory() as db:
        return await db.scalar(select(func.count()).select_from(OATicket).where(OATicket.tenant_id == actor.tenant_id))


async def test_formal_ticket_http_confirm_restart_and_replay(ticket_runtime, monkeypatch):
    factory, first = ticket_runtime
    actor = await owner(factory)
    second = GraphRuntime()
    try:
        async with authenticated_client(factory, monkeypatch, actor) as client:
            identifier, url, data = await open_ticket(client)
            assert await count_tickets(factory, actor) == 0
            await first.close()
            await second.initialize()
            monkeypatch.setattr(thread_service, 'runtime', second)
            monkeypatch.setattr(interrupt_service, 'runtime', second)
            resume_url = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
            request = {'action': 'confirm', 'idempotency_key': 'confirm-once'}
            response = await client.post(resume_url, json=request)
            assert response.status_code == 200, response.text
            detail = await client.get(url)
            assert detail.status_code == 200, detail.text
            ticket = detail.json()['data']['ticket']
            assert ticket['id'] and ticket['state'] == 'OPEN'
            assert detail.json()['data']['business_id'] == ticket['id']
            replay = await client.post(resume_url, json=request)
            assert replay.status_code == 200, replay.text
            assert await count_tickets(factory, actor) == 1
            conflict = await client.post(resume_url, json={**request, 'comment': 'changed'})
            assert conflict.status_code == 409, conflict.text
            async with factory() as db:
                assert await db.scalar(select(func.count()).select_from(TicketRecord).where(TicketRecord.tenant_id == actor.tenant_id)) == 0
                confirmations = (await db.scalars(select(OABridgeConfirmation).where(
                    OABridgeConfirmation.thread_id == identifier))).all()
                assert len(confirmations) == 1 and confirmations[0].consumed_operation_id
    finally:
        await second.close()


async def test_formal_ticket_committed_result_survives_graph_failure(ticket_runtime, monkeypatch):
    factory, runtime = ticket_runtime
    actor = await owner(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_ticket(client)
        original = runtime.resume
        monkeypatch.setattr(runtime, 'resume', AsyncMock(side_effect=RuntimeError('checkpoint unavailable')))
        resume_url = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        request = {'action': 'confirm', 'idempotency_key': 'recover-confirm'}
        response = await client.post(resume_url, json=request)
        assert response.status_code == 200, response.text
        assert await count_tickets(factory, actor) == 1
        detail = await client.get(url)
        assert detail.status_code == 200, detail.text
        assert detail.json()['data']['ticket']['state'] == 'OPEN'
        monkeypatch.setattr(runtime, 'resume', original)
        recovered = await client.post(resume_url, json=request)
        assert recovered.status_code == 200, recovered.text
        assert await count_tickets(factory, actor) == 1
        assert (await client.get(url)).json()['data']['current_interrupt_id'] is None


async def test_formal_ticket_reconciles_when_checkpoint_finishes_before_projection(ticket_runtime, monkeypatch):
    factory, runtime = ticket_runtime
    actor = await owner(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_ticket(client)
        original = runtime.resume
        async def finish_then_fail(*args, **kwargs):
            await original(*args, **kwargs)
            raise RuntimeError('projection unavailable')
        monkeypatch.setattr(runtime, 'resume', finish_then_fail)
        endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        request = {'action': 'confirm', 'idempotency_key': 'projection-recovery'}
        assert (await client.post(endpoint, json=request)).status_code == 200
        monkeypatch.setattr(runtime, 'resume', original)
        assert (await client.post(endpoint, json=request)).status_code == 200
        detail = (await client.get(url)).json()['data']
        assert detail['current_interrupt_id'] is None
        assert detail['error'] is None
        assert detail['ticket']['id'] == detail['business_id']
        assert await count_tickets(factory, actor) == 1


async def test_formal_ticket_pending_message_cannot_replace_confirmed_draft(ticket_runtime, monkeypatch):
    factory, _ = ticket_runtime
    actor = await owner(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_ticket(client)
        duplicate = await client.post(url + '/messages', json={'content': '电脑无法启动，需要维修', 'idempotency_key': 'describe'})
        assert duplicate.status_code == 200
        changed = await client.post(url + '/messages', json={'content': '变成另一个问题', 'idempotency_key': 'another'})
        assert changed.status_code == 409, changed.text
        assert (await client.get(url)).json()['data']['ticket_fields'] == data['ticket_fields']
        endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        assert (await client.post(endpoint, json={'action': 'confirm', 'idempotency_key': 'confirm'})).status_code == 200
        after = await client.post(url + '/messages', json={'content': '再开一单', 'idempotency_key': 'after'})
        assert after.status_code == 409, after.text
        assert await count_tickets(factory, actor) == 1


async def test_formal_ticket_edit_requires_new_confirmation_and_cancel_does_not_write(ticket_runtime, monkeypatch):
    factory, _ = ticket_runtime
    actor = await owner(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_ticket(client)
        response = await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume',
            json={'action': 'edit', 'edited_data': {'summary': '显示器无法点亮'}, 'idempotency_key': 'edit'})
        assert response.status_code == 200, response.text
        edited = (await client.get(url)).json()['data']
        assert edited['ticket_fields']['summary'] == '显示器无法点亮'
        assert edited['current_interrupt_id'] != data['current_interrupt_id']
        cancelled = await client.post('/api/agent/interrupts/' + edited['current_interrupt_id'] + '/resume',
            json={'action': 'cancel', 'idempotency_key': 'cancel'})
        assert cancelled.status_code == 200, cancelled.text
        assert await count_tickets(factory, actor) == 0


@pytest.mark.parametrize('change', ['permission', 'policy', 'tools'])
async def test_formal_ticket_confirmation_rechecks_current_authority(ticket_runtime, monkeypatch, change):
    factory, _ = ticket_runtime
    actor = await owner(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, _, data = await open_ticket(client)
        async with factory() as db:
            if change == 'permission':
                from tests.integration.test_m3_formal_sources import revoke
                await revoke(db, actor, 'ticket')
            else:
                from app.services.oa_scope_service import upsert_formal_policy
                await upsert_formal_policy(db, actor=actor, scene='ticket', scope_type='tenant', scope_value=None,
                    enabled=change != 'policy', thresholds={'allowed_tools': ['get_user_context']} if change == 'tools' else {},
                    rule_version='test')
                await db.commit()
        response = await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume',
            json={'action': 'confirm', 'idempotency_key': 'denied'})
        assert response.status_code in {401, 403, 503}, response.text
        assert await count_tickets(factory, actor) == 0


async def test_formal_ticket_node_cannot_use_forged_checkpoint_confirmation(ticket_runtime):
    factory, _ = ticket_runtime
    actor = await owner(factory)
    set_current_user(actor)
    async with factory() as db:
        thread = await thread_service.create_thread(db, scene='ticket')
        await db.commit()
        state = dict(thread_id=str(thread.id), user_id=actor.user_id, tenant_id=actor.tenant_id, scene='ticket',
            ticket_fields={'summary': 'forged'}, confirmation={'action': 'confirm', 'actor_id': actor.user_id,
                'idempotency_key': 'forged', 'confirmation_id': 'forged'})
        with pytest.raises(AppException):
            await ticket_nodes.create_ticket(state)
        assert await count_tickets(factory, actor) == 0


async def test_formal_ticket_concurrent_confirmation_is_one_command(ticket_runtime, monkeypatch):
    factory, _ = ticket_runtime
    actor = await owner(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        identifier, _, data = await open_ticket(client)
        endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        request = {'action': 'confirm', 'idempotency_key': 'parallel-confirm'}
        responses = await asyncio.gather(client.post(endpoint, json=request), client.post(endpoint, json=request))
        assert [response.status_code for response in responses] == [200, 200]
        assert await count_tickets(factory, actor) == 1
        async with factory() as db:
            decisions = await db.scalar(select(func.count()).select_from(HumanDecision).where(
                HumanDecision.thread_id == UUID(identifier)))
            operations = await db.scalar(select(func.count()).select_from(OAWorkflowOperation).where(
                OAWorkflowOperation.tenant_id == actor.tenant_id, OAWorkflowOperation.kind == 'ticket.create_or_merge'))
            assert decisions == operations == 1


async def test_formal_ticket_other_owner_cannot_read_or_confirm(ticket_runtime, monkeypatch):
    factory, _ = ticket_runtime
    actor = await owner(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_ticket(client)
    async with factory() as db:
        other = await seed(db, tenant=actor.tenant_id, department=actor.depts[0], resources=['thread', 'ticket'])
        await db.commit()
    async with authenticated_client(factory, monkeypatch, other) as client:
        response = await client.get(url)
        assert response.status_code in {403, 404}
        response = await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume',
            json={'action': 'confirm', 'idempotency_key': 'other-owner'})
        assert response.status_code in {403, 404}
        assert await count_tickets(factory, actor) == 0


async def test_formal_ticket_decision_audit_failure_rolls_back_every_write(ticket_runtime, monkeypatch):
    from app.services import audit_service
    from app.models.ticket_draft import TicketDraft
    factory, _ = ticket_runtime
    actor = await owner(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        identifier, _, data = await open_ticket(client)
        original = audit_service.audit
        async def fail_decision(db, action, **kwargs):
            if action == 'human_decided':
                raise RuntimeError('decision audit unavailable')
            return await original(db, action, **kwargs)
        monkeypatch.setattr(audit_service, 'audit', fail_decision)
        with pytest.raises(RuntimeError, match='decision audit unavailable'):
            await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume',
                json={'action': 'confirm', 'idempotency_key': 'rollback'})
        assert await count_tickets(factory, actor) == 0
        async with factory() as db:
            for model in (OAWorkflowOperation, OAWorkflowEvent):
                assert await db.scalar(select(func.count()).select_from(model).where(model.tenant_id == actor.tenant_id)) == 0
            bindings = (await db.scalars(select(OABridgeConfirmation).where(
                OABridgeConfirmation.thread_id == identifier))).all()
            assert len(bindings) == 1 and bindings[0].consumed_operation_id is None
            assert await db.scalar(select(func.count()).select_from(HumanDecision).where(
                HumanDecision.thread_id == UUID(identifier))) == 0
            assert await db.scalar(select(func.count()).select_from(OABusinessAudit).where(
                OABusinessAudit.tenant_id == actor.tenant_id, OABusinessAudit.action == 'human_decided')) == 0
            draft = await db.scalar(select(TicketDraft).where(TicketDraft.thread_id == UUID(identifier)))
            assert draft.status == 'PENDING'


async def test_formal_ticket_extraction_rechecks_permission_after_model(ticket_runtime, monkeypatch):
    from app.llm.base import LLMFactory
    from tests.integration.test_m3_formal_sources import revoke
    from app.models.ticket_draft import TicketDraft
    factory, _ = ticket_runtime
    actor = await owner(factory)
    set_current_user(actor)
    async with factory() as db:
        thread = await thread_service.create_thread(db, scene='ticket')
        await db.commit()
    llm = LLMFactory.get_llm()
    original = llm.structured
    async def revoke_while_generating(*args, **kwargs):
        result = await original(*args, **kwargs)
        async with factory() as db:
            await revoke(db, actor, 'ticket')
        return result
    monkeypatch.setattr(llm, 'structured', revoke_while_generating)
    monkeypatch.setattr(LLMFactory, 'get_llm', lambda: llm)
    state = dict(thread_id=str(thread.id), user_id=actor.user_id, tenant_id=actor.tenant_id, scene='ticket',
        messages=[{'role': 'user', 'content': '电脑无法启动'}])
    with pytest.raises(AppException):
        await ticket_nodes.ticket_extract(state)
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(TicketDraft).where(TicketDraft.thread_id == thread.id)) == 0


@pytest.mark.parametrize('action', ['confirm', 'edit', 'cancel'])
async def test_formal_ticket_reconcile_uses_saved_decision_only(ticket_runtime, monkeypatch, action):
    factory, runtime = ticket_runtime
    actor = await owner(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_ticket(client)
        endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        early = await client.post(endpoint, json={'action': 'reconcile'})
        assert early.status_code == 409, early.text
        original = runtime.resume
        monkeypatch.setattr(runtime, 'resume', AsyncMock(side_effect=RuntimeError('checkpoint unavailable')))
        decision = {'action': action, 'idempotency_key': 'external-client-original-key',
            **({'edited_data': {'summary': '已保存的修改'}} if action == 'edit' else {})}
        response = await client.post(endpoint, json=decision)
        assert response.status_code == 200, response.text
        assert (await client.get(url)).json()['data']['error']['code'] == 'GRAPH_RECOVERY'
        monkeypatch.setattr(runtime, 'resume', original)
        tampered = await client.post(endpoint, json={'action': 'reconcile', 'edited_data': {'summary': '伪造修改'}})
        assert tampered.status_code == 422
        recovered = await client.post(endpoint, json={'action': 'reconcile'})
        assert recovered.status_code == 200, recovered.text
        current = (await client.get(url)).json()['data']
        assert current['error'] is None
        assert await count_tickets(factory, actor) == (1 if action == 'confirm' else 0)
        if action == 'edit':
            assert current['ticket_fields']['summary'] == '已保存的修改'
            assert current['current_interrupt_id'] != data['current_interrupt_id']
        else:
            assert current['current_interrupt_id'] is None
        assert (await client.post(endpoint, json={'action': 'reconcile'})).status_code == 200


async def existing_ticket(factory, actor):
    from app.schemas.oa_ticket import FormalTicketProposal
    from app.services import oa_ticket_service
    async with factory() as db:
        proposal = FormalTicketProposal(operation_id='existing', summary='电脑无法启动，需要维修')
        binding = await oa_ticket_service.prepare(db, actor, proposal)
        result = await oa_ticket_service.create_or_merge(db, actor, proposal,
            confirmation_id=binding['confirmation_id'])
        await db.commit()
        return result.result


async def select_duplicate(client, data, target):
    response = await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume',
        json={'action': 'edit', 'edited_data': {'merge_ticket_id': target['id'],
            'expected_revision': target['revision']}, 'idempotency_key': 'choose-target'})
    return response


async def test_formal_ticket_duplicate_selection_requires_fresh_confirmation(ticket_runtime, monkeypatch):
    factory, _ = ticket_runtime
    actor = await owner(factory)
    target = await existing_ticket(factory, actor)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_ticket(client)
        assert [row['id'] for row in data['ticket_candidates']] == [target['id']]
        assert data['ticket_review']['mode'] == 'new'
        chosen = await select_duplicate(client, data, target)
        assert chosen.status_code == 200, chosen.text
        selected = (await client.get(url)).json()['data']
        assert selected['current_interrupt_id'] != data['current_interrupt_id']
        assert selected['ticket_review']['mode'] == 'merge'
        assert selected['ticket_review']['target_ticket_id'] == target['id']
        assert await count_tickets(factory, actor) == 1
        old = await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume',
            json={'action': 'confirm', 'idempotency_key': 'old-confirm'})
        assert old.status_code == 409
        endpoint = '/api/agent/interrupts/' + selected['current_interrupt_id'] + '/resume'
        request = {'action': 'confirm', 'idempotency_key': 'merge-confirm'}
        result = await client.post(endpoint, json=request)
        assert result.status_code == 200, result.text
        assert (await client.post(endpoint, json=request)).status_code == 200
        final = (await client.get(url)).json()['data']
        assert final['ticket']['id'] == target['id']
        assert final['ticket']['merged'] is True
        assert final['ticket']['revision'] == target['revision'] + 1
        assert len(final['ticket']['merged_requests']) == 1
        assert await count_tickets(factory, actor) == 1


@pytest.mark.parametrize('merge', [False, True])
async def test_formal_ticket_duplicate_choice_can_still_create_new(ticket_runtime, monkeypatch, merge):
    factory, _ = ticket_runtime
    actor = await owner(factory)
    target = await existing_ticket(factory, actor)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_ticket(client)
        if merge:
            chosen = await select_duplicate(client, data, target)
            assert chosen.status_code == 200, chosen.text
            data = (await client.get(url)).json()['data']
            response = await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume',
                json={'action': 'edit', 'edited_data': {'merge_ticket_id': None, 'expected_revision': None}})
            assert response.status_code == 200, response.text
            data = (await client.get(url)).json()['data']
        assert data['ticket_review']['mode'] == 'new'
        response = await client.post('/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume',
            json={'action': 'confirm'})
        assert response.status_code == 200, response.text
        final = (await client.get(url)).json()['data']
        assert final['ticket']['id'] != target['id']
        assert final['ticket']['merged'] is False
        assert await count_tickets(factory, actor) == 2


@pytest.mark.parametrize('change', ['revision', 'closed'])
async def test_formal_ticket_merge_rechecks_reviewed_target(ticket_runtime, monkeypatch, change):
    factory, _ = ticket_runtime
    actor = await owner(factory)
    target = await existing_ticket(factory, actor)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        identifier, url, data = await open_ticket(client)
        chosen = await select_duplicate(client, data, target)
        assert chosen.status_code == 200, chosen.text
        selected = (await client.get(url)).json()['data']
        async with factory() as db:
            row = await db.get(OATicket, target['id'])
            row.revision += 1
            if change == 'closed':
                row.state = 'CLOSED'
            await db.commit()
        current = (await client.get(url)).json()['data']
        assert current['ticket_review']['changed'] is True
        rejected = await client.post('/api/agent/interrupts/' + selected['current_interrupt_id'] + '/resume',
            json={'action': 'confirm'})
        assert rejected.status_code == 409, rejected.text
        async with factory() as db:
            assert (await db.get(OATicket, target['id'])).merged_requests == []
            assert await db.scalar(select(func.count()).select_from(HumanDecision).where(
                HumanDecision.thread_id == UUID(identifier), HumanDecision.action == 'confirm')) == 0


@pytest.mark.parametrize('same_tenant', [True, False])
async def test_formal_ticket_candidates_and_selection_reject_other_owner(ticket_runtime, monkeypatch, same_tenant):
    factory, _ = ticket_runtime
    actor = await owner(factory)
    async with factory() as db:
        peer = await seed(db, tenant=actor.tenant_id if same_tenant else None, resources=['thread', 'ticket'])
        await db.commit()
    foreign = await existing_ticket(factory, peer)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        _, url, data = await open_ticket(client)
        assert data['ticket_candidates'] == []
        response = await select_duplicate(client, data, foreign)
        assert response.status_code == (403 if same_tenant else 404), response.text
        assert (await client.get(url)).json()['data']['current_interrupt_id'] == data['current_interrupt_id']
        assert await count_tickets(factory, actor) == int(same_tenant)
        async with factory() as db:
            assert (await db.get(OATicket, foreign['id'])).merged_requests == []


async def test_formal_ticket_expired_review_needs_explicit_refresh(ticket_runtime, monkeypatch):
    from datetime import datetime, timedelta, timezone
    factory, _ = ticket_runtime
    actor = await owner(factory)
    async with authenticated_client(factory, monkeypatch, actor) as client:
        identifier, url, data = await open_ticket(client)
        async with factory() as db:
            binding = await db.scalar(select(OABridgeConfirmation).where(OABridgeConfirmation.thread_id == identifier))
            assert binding is not None
            binding.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        endpoint = '/api/agent/interrupts/' + data['current_interrupt_id'] + '/resume'
        response = await client.post(endpoint, json={'action': 'confirm'})
        assert response.status_code == 422, response.text
        assert await count_tickets(factory, actor) == 0
        response = await client.post(endpoint, json={'action': 'edit', 'edited_data': {}})
        assert response.status_code == 200, response.text
        refreshed = (await client.get(url)).json()['data']
        assert refreshed['current_interrupt_id'] != data['current_interrupt_id']
        response = await client.post('/api/agent/interrupts/' + refreshed['current_interrupt_id'] + '/resume',
            json={'action': 'confirm'})
        assert response.status_code == 200, response.text
        assert await count_tickets(factory, actor) == 1


async def test_formal_ticket_merge_review_and_committed_result_survive_runtime_restarts(ticket_runtime, monkeypatch):
    factory, first = ticket_runtime
    actor = await owner(factory)
    target = await existing_ticket(factory, actor)
    second, third = GraphRuntime(), GraphRuntime()
    try:
        async with authenticated_client(factory, monkeypatch, actor) as client:
            _, url, data = await open_ticket(client)
            chosen = await select_duplicate(client, data, target)
            assert chosen.status_code == 200, chosen.text
            reviewed = (await client.get(url)).json()['data']
            await first.close()
            await second.initialize()
            monkeypatch.setattr(thread_service, 'runtime', second)
            monkeypatch.setattr(interrupt_service, 'runtime', second)
            restored = (await client.get(url)).json()['data']
            assert restored['ticket_review']['mode'] == 'merge'
            assert restored['current_interrupt_id'] == reviewed['current_interrupt_id']
            monkeypatch.setattr(second, 'resume', AsyncMock(side_effect=RuntimeError('checkpoint unavailable')))
            endpoint = '/api/agent/interrupts/' + restored['current_interrupt_id'] + '/resume'
            confirmed = await client.post(endpoint, json={'action': 'confirm', 'idempotency_key': 'durable-merge'})
            assert confirmed.status_code == 200, confirmed.text
            failed_graph = (await client.get(url)).json()['data']
            assert failed_graph['error']['code'] == 'GRAPH_RECOVERY'
            assert failed_graph['ticket']['merged'] is True
            await second.close()
            await third.initialize()
            monkeypatch.setattr(thread_service, 'runtime', third)
            monkeypatch.setattr(interrupt_service, 'runtime', third)
            for _ in range(2):
                reconciled = await client.post(endpoint, json={'action': 'reconcile'})
                assert reconciled.status_code == 200, reconciled.text
            final = (await client.get(url)).json()['data']
            assert final['error'] is None
            assert final['current_interrupt_id'] is None
            assert final['ticket']['id'] == target['id']
            assert final['ticket']['merged'] is True
            assert final['ticket']['revision'] == target['revision'] + 1
            assert len(final['ticket']['merged_requests']) == 1
            assert await count_tickets(factory, actor) == 1
    finally:
        await second.close()
        await third.close()
