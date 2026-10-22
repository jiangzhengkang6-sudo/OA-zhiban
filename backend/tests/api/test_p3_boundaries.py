"""Scene isolation and controlled degradation against real HTTP services."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import text

from app.db.session import engine, async_session_factory
from app.main import app
from app.models.ticket_record import TicketRecord
from app.services import policy_service, degradation_service

EMP = {'Authorization': 'Bearer mock:u_emp_001'}
INPUTS = {
    'work_task': ('/api/work-tasks/batches', {'source_type': 'ticket', 'source_id': 'P3-ISOLATION'}),
    'report': ('/api/reports', {'subject': 'Isolation', 'plan': {
        'metrics': ['ticket_volume'], 'start': '2026-10-01', 'end': '2026-10-15', 'scope': 'own'}}),
    'contract': ('/api/contracts', {'title': 'Isolation', 'reviewer_id': 'u_mgr_001', 'text': 'Payment terms.'}),
}


@pytest.fixture
async def boundary_client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text('TRUNCATE agent_thread, ticket_record, idempotency_record, agent_policy, policy_version, degradation_state RESTART IDENTITY CASCADE'))
    async with async_session_factory() as session:
        session.add(TicketRecord(tenant_id='t_001', user_id='u_emp_001', ticket_id='P3-ISOLATION',
            category='other', priority='medium', impact='individual', summary='Authorized source',
            status='open', idempotency_key='isolation-seed', payload_hash='isolation'))
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client


@pytest.mark.asyncio
@pytest.mark.parametrize('disabled', INPUTS)
@pytest.mark.parametrize('mode', ['policy', 'degradation'])
async def test_one_scene_disabled_preserves_other_scenes_and_p1_p2(boundary_client, monkeypatch, disabled, mode):
    if mode == 'policy':
        original = policy_service.is_scene_enabled
        async def enabled(session, scene, *args, **kwargs):
            return False if scene == disabled else await original(session, scene, *args, **kwargs)
        monkeypatch.setattr(policy_service, 'is_scene_enabled', enabled)
    else:
        original = degradation_service.resolve
        async def resolve(session, *, scene, user):
            if scene == disabled:
                return SimpleNamespace(new_task_action='pause', inflight_action='pause',
                    created_at=datetime.now(timezone.utc) - timedelta(hours=1))
            return await original(session, scene=scene, user=user)
        monkeypatch.setattr(degradation_service, 'resolve', resolve)
    for scene, (path, payload) in INPUTS.items():
        response = await boundary_client.post(path, headers=EMP,
            json={**payload, 'idempotency_key': f'{mode}-{disabled}-{scene}'})
        assert response.status_code == (503 if scene == disabled else 200), response.text
    for scene in ['faq', 'ticket', 'leave']:
        response = await boundary_client.post('/api/agent/threads', headers=EMP,
            json={'scene': scene, **({'business_id': 'LV-OK-001'} if scene == 'leave' else {})})
        assert response.status_code == 200, response.text
    legacy = [
        ('/api/meetings', {'title': 'Isolation', 'content': 'Review source'}),
        ('/api/documents', {'template_id': 'notice', 'subject': 'Isolation', 'recipient': 'Project team',
            'deadline': 'Friday', 'basis': 'Project plan', 'key_points': 'Review source', 'classification': 'internal',
            'distribution': 'Internal project team'}),
        ('/api/emails', {'subject': 'Isolation', 'sender': 'test@example.com', 'recipients': ['team@company.test'],
            'body': 'Review source', 'external_contact': False, 'attachments': []}),
    ]
    for path, payload in legacy:
        response = await boundary_client.post(path, headers=EMP,
            json={**payload, 'idempotency_key': f'{mode}-{disabled}-{path}'})
        assert response.status_code == 200, response.text


@pytest.mark.asyncio
@pytest.mark.parametrize('disabled', ['report', 'contract'])
async def test_disabled_scene_blocks_existing_generation_but_preserves_reads(boundary_client, monkeypatch, disabled):
    path, payload = INPUTS[disabled]
    created = await boundary_client.post(path, headers=EMP, json={**payload, 'idempotency_key': 'before-disable'})
    assert created.status_code == 200, created.text
    record = created.json()['data']
    monkeypatch.setattr(policy_service, 'is_scene_enabled', AsyncMock(return_value=False))
    resource = path + '/' + record[disabled + '_id']
    response = await boundary_client.get(resource, headers=EMP)
    assert response.status_code == 200, response.text
    command = {'expected_version': record['version'], 'idempotency_key': 'blocked'}
    command.update({'plan_confirmed': True} if disabled == 'report' else {'action': 'review'})
    response = await boundary_client.post(resource + ('/approve-plan' if disabled == 'report' else '/commands'),
        headers=EMP, json=command)
    assert response.status_code == 503, response.text
