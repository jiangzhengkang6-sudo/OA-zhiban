import httpx
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
from uuid import UUID
from sqlalchemy import select, text
from app.db.session import engine, async_session_factory
from app.main import app
from app.models.contract_record import ContractRecord
from app.models.agent_thread import AgentThread
from app.models.contract_review_version import ContractReviewVersion
from app.services import runtime_trace_service, contract_service

EMP = {'Authorization': 'Bearer mock:u_emp_001'}
MGR = {'Authorization': 'Bearer mock:u_mgr_001'}
ADMIN = {'Authorization': 'Bearer mock:u_admin_001'}


@pytest.fixture
async def contract_client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text('TRUNCATE agent_thread, idempotency_record, audit_event, runtime_span, agent_policy, policy_version, degradation_state RESTART IDENTITY CASCADE'))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        yield client


async def create(client, text='付款条款：30日付款。\n违约责任：协商赔偿。\n终止条款：提前通知。\n争议解决：法院起诉。', key='contract-create'):
    res = await client.post('/api/contracts', headers=EMP, json={'title':'采购合同', 'reviewer_id':'u_mgr_001', 'text':text, 'idempotency_key':key})
    assert res.status_code == 200, res.text
    return res.json()['data']


async def command(client, record, action, key, headers=EMP, **kwargs):
    return await client.post(f"/api/contracts/{record['contract_id']}/commands", headers=headers, json={'action':action, 'idempotency_key':key, 'expected_version':record['version'], **kwargs})


@pytest.mark.asyncio
async def test_private_contract_lifecycle_and_decision_ledger(contract_client):
    created = await create(contract_client)
    assert created['status'] == 'CREATED'
    assert (await contract_client.get('/api/contracts/' + created['contract_id'], headers=ADMIN)).status_code == 404
    reviewed = await command(contract_client, created, 'review', 'review')
    assert reviewed.status_code == 200, reviewed.text
    record = reviewed.json()['data']
    assert record['status'] == 'DRAFT_READY'
    assert record['node_trace'] == ['extract_clauses', 'check_rules', 'analyze_risks', 'summarize']
    assert len(record['draft']['risks']) == 4
    assert (await command(contract_client, record, 'confirm', 'owner', dispositions=[])).status_code == 403
    dispositions = [{'risk_id':r['risk_id'], 'action':'accepted', 'comment':'人工核对原文'} for r in record['draft']['risks']]
    decided = await command(contract_client, record, 'confirm', 'decide', headers=MGR, dispositions=dispositions, comment='通过内部审查')
    assert decided.status_code == 200, decided.text
    assert decided.json()['data']['status'] == 'CONFIRMED'
    replay = await command(contract_client, record, 'confirm', 'decide', headers=MGR, dispositions=dispositions, comment='通过内部审查')
    assert replay.json() ['data'] == decided.json()['data']
    assert (await command(contract_client, decided.json()['data'], 'review', 'terminal')).status_code == 422
    bypass = await contract_client.post(f"/api/agent/threads/{record['thread_id']}/messages", headers=EMP, json={'content':'确认','idempotency_key':'bypass'})
    assert bypass.status_code == 422


@pytest.mark.asyncio
async def test_upload_pending_and_long_document_deepagents(contract_client):
    uploaded = await contract_client.post('/api/contracts/uploads', headers=EMP, data={'title':'文件合同', 'reviewer_id':'u_mgr_001', 'idempotency_key':'upload'}, files={'file':('x.txt','付款条款：30日付款。'.encode(), 'text/plain')})
    assert uploaded.status_code == 200, uploaded.text
    record = uploaded.json()['data']
    assert record['scan_status'] == 'PENDING'
    assert (await command(contract_client, record, 'review', 'pending')).status_code == 422
    long = await create(contract_client, text=('付款条款：30日付款。\n' * 1000), key='long')
    result = await command(contract_client, long, 'review', 'long-review')
    assert result.status_code == 200, result.text
    assert result.json()['data']['draft']['analysis_engine'] == 'deepagents'


@pytest.mark.asyncio
async def test_contract_versions_conflicts_and_risk_completeness(contract_client):
    created = await create(contract_client)
    assert created['version'] == 0
    record = (await command(contract_client, created, 'review', 'review')).json()['data']
    saved = await command(contract_client, record, 'save', 'save', summary='人工修订摘要')
    assert saved.status_code == 200, saved.text
    latest = saved.json()['data']
    assert latest['version'] == 2
    assert (await command(contract_client, record, 'save', 'stale', summary='stale')).status_code == 409
    assert (await command(contract_client, record, 'save', 'save', summary='changed')).status_code == 409
    assert (await command(contract_client, latest, 'confirm', 'missing', headers=MGR,
        dispositions=[], comment='checked')).status_code == 422
    versions = (await contract_client.get(f"/api/contracts/{created['contract_id']}/versions", headers=EMP)).json()['data']
    assert [v['version'] for v in versions] == [1, 2]
    assert versions[0]['draft']['summary'] != versions[1]['draft']['summary']
    assert versions[0]['draft']['risks'] == versions[1]['draft']['risks']


@pytest.mark.asyncio
async def test_contract_model_failure_retries_only_remaining_nodes(contract_client, monkeypatch):
    from app.graph import contract_graph as module
    original = module.analyze_long_contract
    monkeypatch.setattr(module, 'analyze_long_contract', AsyncMock(side_effect=ValueError('PRIVATE RAW ERROR')))
    created = await create(contract_client, text='付款条款。\n' * 1800)
    response = await command(contract_client, created, 'review', 'fail')
    assert response.status_code == 200, response.text
    paused = response.json()['data']
    assert paused['status'] == 'PAUSED'
    assert paused['node_trace'] == ['extract_clauses', 'check_rules']
    assert 'PRIVATE RAW ERROR' not in str(paused)
    monkeypatch.setattr(module, 'analyze_long_contract', original)
    retried = await command(contract_client, paused, 'retry', 'retry')
    assert retried.status_code == 200, retried.text
    assert retried.json()['data']['status'] == 'DRAFT_READY'
    assert len(retried.json()['data']['node_trace']) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['checkpoint', 'finalize'])
async def test_contract_db_failure_is_not_model_failure_and_stale_run_recovers(contract_client, monkeypatch, fault):
    created = await create(contract_client)
    if fault == 'checkpoint':
        original = runtime_trace_service.record_span
        monkeypatch.setattr(runtime_trace_service, 'record_span', AsyncMock(side_effect=RuntimeError('DB unavailable')))
    else:
        original = contract_service._finish
        async def fail_finish(*args, **kwargs):
            raise RuntimeError('DB unavailable')
        monkeypatch.setattr(contract_service, '_finish', fail_finish)
    with pytest.raises(RuntimeError, match='DB unavailable'):
        await command(contract_client, created, 'review', 'db-fail')
    async with async_session_factory() as session:
        row = await session.scalar(select(ContractRecord).where(ContractRecord.contract_id == created['contract_id']))
        assert row.status == 'PROCESSING' and row.error_message is None
        assert (await session.scalars(select(ContractReviewVersion).where(ContractReviewVersion.contract_id == row.id))).all() == []
        row.updated_at = datetime.now(timezone.utc) - timedelta(seconds=140)
        await session.commit()
    monkeypatch.setattr(runtime_trace_service if fault == 'checkpoint' else contract_service,
        'record_span' if fault == 'checkpoint' else '_finish', original)
    state = (await contract_client.get('/api/contracts/' + created['contract_id'], headers=EMP)).json()['data']
    recovered = await command(contract_client, state, 'retry', 'db-retry')
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()['data']['status'] == 'DRAFT_READY'
    versions = (await contract_client.get(f"/api/contracts/{created['contract_id']}/versions", headers=EMP)).json()['data']
    assert [v['version'] for v in versions] == [1]


@pytest.mark.asyncio
async def test_contract_reviewer_revocation_blocks_all_private_reads_and_replay(contract_client, monkeypatch):
    from app.adapters.factory import get_adapter
    created = await create(contract_client)
    record = (await command(contract_client, created, 'review', 'review')).json()['data']
    dispositions = [{'risk_id': r['risk_id'], 'action':'accepted', 'comment':'checked'} for r in record['draft']['risks']]
    decided = await command(contract_client, record, 'confirm', 'decide', headers=MGR, dispositions=dispositions, comment='checked')
    assert decided.status_code == 200
    adapter = get_adapter()
    original = adapter.get_user_context
    def context(user_id):
        value = original(user_id)
        return value.model_copy(update={'roles':['employee']}) if user_id == 'u_mgr_001' else value
    monkeypatch.setattr(adapter, 'get_user_context', context)
    for suffix in ['', '/versions', '/sources/' + record['source_id']]:
        assert (await contract_client.get('/api/contracts/' + record['contract_id'] + suffix, headers=MGR)).status_code == 404
    assert (await command(contract_client, record, 'confirm', 'decide', headers=MGR,
        dispositions=dispositions, comment='checked')).status_code == 404
    thread = await contract_client.get('/api/agent/threads/' + record['thread_id'], headers=MGR)
    assert thread.status_code in [403, 404]


@pytest.mark.asyncio
async def test_contract_generic_thread_redacts_body_and_disallows_resume(contract_client):
    created = await create(contract_client)
    detail = await contract_client.get('/api/agent/threads/' + created['thread_id'], headers=EMP)
    assert detail.status_code == 200, detail.text
    assert created['source_text'] not in detail.text
    assert detail.json()['data']['messages'] == []
    async with async_session_factory() as session:
        thread = await session.get(AgentThread, UUID(created['thread_id']))
        thread.current_interrupt_id = 'contract-bypass'
        await session.commit()
    resume = await contract_client.post('/api/agent/interrupts/contract-bypass/resume', headers=EMP,
        json={'idempotency_key':'bypass','action':'confirm'})
    assert resume.status_code == 422
