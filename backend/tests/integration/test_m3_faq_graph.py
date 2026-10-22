"""Formal FAQ executes the graph with real scoped rows and Mock model channels."""
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core import config
from app.core.context import get_current_user, set_current_user
from app.core.errors import AppException
from app.graph.nodes import common, faq_nodes
from app.graph.superagent import build_superagent
from app.llm.base import LLMFactory
from app.models.agent_thread import AgentThread
from app.models.knowledge_source import KnowledgeSource
from app.models.knowledge_version import KnowledgeVersion
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.oa_ai_scope import OABusinessAudit, OAKnowledgeBinding
from app.services import knowledge_service, oa_scope_service, thread_service, policy_service
from app.providers import identity
from tests.oa_support import oa_db, seed


@pytest.fixture
def formal_nodes(oa_db, monkeypatch):
    settings = policy_service.get_settings()
    monkeypatch.setattr(settings, 'oa_provider', 'builtin')
    monkeypatch.setattr(settings, 'auth_provider', 'builtin')
    monkeypatch.setattr(config, 'get_settings', lambda: settings)
    monkeypatch.setattr(identity, 'get_settings', lambda: settings)
    monkeypatch.setattr(common, 'async_session_factory', oa_db)
    monkeypatch.setattr(faq_nodes, 'async_session_factory', oa_db)
    monkeypatch.setattr(common, 'get_adapter', lambda: pytest.fail('formal graph called legacy adapter'))
    previous = get_current_user()
    yield oa_db
    set_current_user(previous)


async def fixture(db):
    actor = await seed(db, resources=['knowledge', 'thread'])
    thread = AgentThread(tenant_id=actor.tenant_id, user_id=actor.user_id, scene='faq', status='DRAFT')
    source = KnowledgeSource(tenant_id=actor.tenant_id, name='报销制度', owner_id=actor.user_id)
    db.add_all([thread, source])
    await db.flush()
    version = KnowledgeVersion(source_id=source.id, version=1, status='published', parse_status='READY', permission_tags=[])
    db.add(version)
    await db.flush()
    content = '公司的报销制度是什么？'
    vector = (await LLMFactory.get_embedding().embed([content]))[0]
    chunk = KnowledgeChunk(document_id=source.id, version_id=version.id, content=content,
        content_hash=sha256(content.encode()).hexdigest(), embedding=vector, source_location='制度第一条')
    db.add(chunk)
    binding = await oa_scope_service.create_binding(db, actor=actor, source_id=source.id, owner_id=actor.user_id,
        department_id=actor.depts[0], access_scope='owner')
    await db.commit()
    set_current_user(actor)
    state = dict(thread_id=str(thread.id), tenant_id=actor.tenant_id, user_id=actor.user_id, scene='faq',
        messages=[{'role': 'user', 'content': content}], policy={'thresholds': {'faq_answer': 0}},
        permissions={'roles': ['admin'], 'dept_id': 'forged'}, intent='faq')
    return actor, thread, binding, chunk, state


async def test_formal_faq_graph_uses_live_context_sources_and_formal_audit(formal_nodes):
    async with formal_nodes() as db:
        actor, _, _, chunk, state = await fixture(db)
        result = await build_superagent().compile().ainvoke(state)
        assert result['next_action'] == 'answered'
        assert result['permissions']['dept_id'] == actor.depts[0]
        source = result['answer']['sources'][0]
        assert source['chunk_id'] == str(chunk.id)
        assert source['version_id'] == str(chunk.version_id)
        audits = (await db.scalars(select(OABusinessAudit).where(OABusinessAudit.tenant_id == actor.tenant_id))).all()
        assert audits and all(row.resource == 'knowledge' for row in audits)


async def test_formal_faq_thread_can_open_and_cached_answer_is_hidden_when_source_revoked(formal_nodes, monkeypatch):
    async with formal_nodes() as db:
        actor, thread, binding, _, state = await fixture(db)
        created = await thread_service.create_thread(db, scene='faq')
        assert created.scene == 'faq' and created.tenant_id == actor.tenant_id
        await db.commit()
        result = await build_superagent().compile().ainvoke(state)
        monkeypatch.setattr(thread_service.runtime, 'get_state', AsyncMock(return_value=SimpleNamespace(values=result, tasks=[])))
        monkeypatch.setattr(type(thread_service.runtime), 'ready', property(lambda self: True))
        assert await thread_service.can_view_thread(thread, actor, db)
        assert (await thread_service.build_thread_detail(db, thread)).answer
        binding.status = 'revoked'
        await db.commit()
        detail = await thread_service.build_thread_detail(db, thread)
        assert detail.answer is None


@pytest.mark.parametrize('field', ['user_id', 'tenant_id'])
async def test_formal_graph_rejects_forged_checkpoint_actor(formal_nodes, field):
    async with formal_nodes() as db:
        _, _, _, _, state = await fixture(db)
        state[field] = 'forged'
        with pytest.raises(AppException) as denied:
            await common.load_context(state)
        assert denied.value.http_status == 403


async def test_formal_faq_rechecks_binding_before_generation(formal_nodes, monkeypatch):
    async with formal_nodes() as db:
        _, _, binding, _, state = await fixture(db)
        state.update(await faq_nodes.faq_retrieve(state))
        assert state['faq_chunks']
        binding.status = 'revoked'
        await db.commit()
        monkeypatch.setattr(LLMFactory, 'get_llm', lambda: pytest.fail('revoked source reached model'))
        result = await faq_nodes.faq_answer(state)
        assert result['answer'] is None and result['faq_chunks'] == []


async def test_formal_faq_rehydrates_checkpoint_evidence_from_database(formal_nodes):
    async with formal_nodes() as db:
        _, _, _, chunk, state = await fixture(db)
        state.update(await faq_nodes.faq_retrieve(state))
        state['faq_chunks'][0]['content'] = '伪造的图缓存正文'
        result = await faq_nodes.faq_answer(state)
        assert result['faq_chunks'][0]['content'] == chunk.content
        assert '伪造' not in result['answer']['answer']


async def test_formal_faq_denies_knowledge_revocation_before_embedding(formal_nodes, monkeypatch):
    from tests.integration.test_m3_formal_sources import revoke
    async with formal_nodes() as db:
        actor, _, _, _, _ = await fixture(db)
        await revoke(db, actor, 'knowledge')
        monkeypatch.setattr(LLMFactory, 'get_embedding', lambda: pytest.fail('denied query reached embedding'))
        with pytest.raises(AppException) as denied:
            await knowledge_service.search(db, query='制度', permission_tags=[])
        assert denied.value.http_status == 403


async def set_policy(db, actor, *, enabled=True, **thresholds):
    await oa_scope_service.upsert_formal_policy(db, actor=actor, scene='faq', scope_type='tenant',
        scope_value=None, enabled=enabled, thresholds=thresholds, rule_version='boundary-test')
    await db.commit()


@pytest.mark.parametrize('during_call', [False, True])
async def test_formal_classifier_rechecks_policy_switch_at_model_boundary(formal_nodes, monkeypatch, during_call):
    async with formal_nodes() as db:
        actor, _, _, _, state = await fixture(db)
        state.update(await common.load_context(state))
        async def classify(*args):
            await set_policy(db, actor, enabled=False)
            return SimpleNamespace(intent='faq', confidence=0.9)
        if during_call:
            monkeypatch.setattr(LLMFactory, 'get_llm', lambda: SimpleNamespace(structured=classify))
        else:
            await set_policy(db, actor, enabled=False)
            monkeypatch.setattr(LLMFactory, 'get_llm', lambda: pytest.fail('disabled policy reached model'))
        with pytest.raises(AppException) as denied:
            await common.classify_intent(state)
        assert denied.value.http_status == 503


@pytest.mark.parametrize('during_call', [False, True])
async def test_formal_classifier_uses_current_confidence_threshold(formal_nodes, monkeypatch, during_call):
    async with formal_nodes() as db:
        actor, _, _, _, state = await fixture(db)
        state.update(await common.load_context(state))
        async def classify(*args):
            if during_call:
                await set_policy(db, actor, intent_confidence=0.95)
            return SimpleNamespace(intent='faq', confidence=0.8)
        if not during_call:
            await set_policy(db, actor, intent_confidence=0.95)
        monkeypatch.setattr(LLMFactory, 'get_llm', lambda: SimpleNamespace(structured=classify))
        result = await common.classify_intent(state)
        assert result['intent'] == 'human'


async def test_formal_retrieval_uses_current_answer_threshold(formal_nodes):
    async with formal_nodes() as db:
        actor, _, _, _, state = await fixture(db)
        await set_policy(db, actor, faq_answer=0.95)
        state['question'] = '不同的检索文本'
        result = await faq_nodes.faq_retrieve(state)
        assert result['next_action'] == 'human' and result['answer'] is None


@pytest.mark.parametrize('change', ['binding', 'permission', 'policy', 'threshold'])
async def test_formal_answer_rechecks_changes_during_model_call(formal_nodes, monkeypatch, change):
    from tests.integration.test_m3_formal_sources import revoke
    async with formal_nodes() as db:
        actor, _, binding, _, state = await fixture(db)
        state.update(await faq_nodes.faq_retrieve(state))
        assert state['faq_chunks']
        # A score below the new threshold proves a cached policy cannot authorize an answer.
        state['faq_chunks'][0]['similarity'] = 0.8
        async def generate(*args):
            if change == 'binding':
                binding.status = 'revoked'
                await db.commit()
            elif change == 'permission':
                await revoke(db, actor, 'knowledge')
            elif change == 'policy':
                await set_policy(db, actor, enabled=False)
            else:
                await set_policy(db, actor, faq_answer=0.95)
            return '应被丢弃的生成内容'
        monkeypatch.setattr(faq_nodes, 'get_settings', lambda: SimpleNamespace(oa_provider='builtin', llm_provider='test'))
        monkeypatch.setattr(LLMFactory, 'get_llm', lambda: SimpleNamespace(chat=generate))
        if change == 'policy':
            with pytest.raises(AppException) as denied:
                await faq_nodes.faq_answer(state)
            assert denied.value.http_status == 503
        else:
            result = await faq_nodes.faq_answer(state)
            assert result['answer'] is None and result['faq_chunks'] == []


async def test_formal_search_rechecks_permission_after_embedding(formal_nodes, monkeypatch):
    from tests.integration.test_m3_formal_sources import revoke
    async with formal_nodes() as db:
        actor, _, _, chunk, _ = await fixture(db)
        async def embed(*args):
            async with formal_nodes() as mutation:
                await revoke(mutation, actor, 'knowledge')
            return [list(chunk.embedding)]
        monkeypatch.setattr(LLMFactory, 'get_embedding', lambda: SimpleNamespace(embed=embed))
        with pytest.raises(AppException) as denied:
            await knowledge_service.search(db, query='制度', permission_tags=actor.depts)
        assert denied.value.http_status == 403


@pytest.mark.parametrize('change', ['policy', 'threshold', 'tools'])
async def test_formal_cached_answer_rechecks_current_policy(formal_nodes, monkeypatch, change):
    async with formal_nodes() as db:
        actor, thread, _, _, state = await fixture(db)
        result = await build_superagent().compile().ainvoke(state)
        assert result['answer']
        result['answer']['sources'][0]['similarity'] = 0.8
        result['answer']['confidence'] = 0.8
        monkeypatch.setattr(thread_service.runtime, 'get_state', AsyncMock(return_value=SimpleNamespace(values=result, tasks=[])))
        monkeypatch.setattr(type(thread_service.runtime), 'ready', property(lambda self: True))
        if change == 'policy':
            await set_policy(db, actor, enabled=False)
        elif change == 'threshold':
            await set_policy(db, actor, faq_answer=0.95)
        else:
            await set_policy(db, actor, allowed_tools=['get_user_context'])
        detail = await thread_service.build_thread_detail(db, thread)
        assert detail.answer is None
        assert detail.next_action == 'human'


async def test_formal_faq_http_postgres_restart_and_replay(formal_nodes, monkeypatch):
    from app.graph.graph_service import GraphRuntime
    from app.models.agent_message import AgentMessage
    from tests.m3_http_support import authenticated_client
    async with formal_nodes() as db:
        actor, _, binding, chunk, state = await fixture(db)
    first = GraphRuntime()
    second = GraphRuntime()
    try:
        await first.initialize()
        monkeypatch.setattr(thread_service, 'runtime', first)
        async with authenticated_client(formal_nodes, monkeypatch, actor) as client:
            created = await client.post('/api/agent/threads', json={'scene': 'faq'})
            assert created.status_code == 200, created.text
            identifier = created.json()['data']['thread_id']
            url = f'/api/agent/threads/{identifier}'
            message = {'content': state['messages'][0]['content'], 'idempotency_key': 'durable-faq'}
            sent = await client.post(url + '/messages', json=message)
            assert sent.status_code == 200, sent.text
            assert sent.json()['data']['next_action'] == 'answered'
            before = await client.get(url)
            assert before.status_code == 200, before.text
            assert before.json()['data']['answer']['sources'][0]['chunk_id'] == str(chunk.id)
            snapshot = await first.get_state(identifier)
            assert snapshot.config['configurable']['checkpoint_id']
            await first.close()
            await second.initialize()
            monkeypatch.setattr(thread_service, 'runtime', second)
            restored = await second.get_state(identifier)
            assert restored.values['answer'] == snapshot.values['answer']
            assert restored.config['configurable']['checkpoint_id'] == snapshot.config['configurable']['checkpoint_id']
            after = await client.get(url)
            assert after.status_code == 200 and after.json()['data']['answer'] == before.json()['data']['answer']
            replay = await client.post(url + '/messages', json=message)
            assert replay.status_code == 200, replay.text
            assert replay.json()['data']['message_id'] == sent.json()['data']['message_id']
            from uuid import UUID
            async with formal_nodes() as db:
                rows = (await db.scalars(select(AgentMessage).where(AgentMessage.thread_id == UUID(identifier)))).all()
                assert len([row for row in rows if row.role == 'user']) == 1
                binding_row = await db.get(OAKnowledgeBinding, binding.id)
                binding_row.status = 'revoked'
                await db.commit()
            hidden = await client.get(url)
            assert hidden.status_code == 200, hidden.text
            assert hidden.json()['data']['answer'] is None
            assert hidden.json()['data']['next_action'] == 'human'
            async with formal_nodes() as db:
                from tests.integration.test_m3_formal_sources import revoke
                await revoke(db, actor, 'knowledge')
            denied = await client.get(url)
            assert denied.status_code == 403, denied.text
            replay_denied = await client.post(url + '/messages', json=message)
            assert replay_denied.status_code == 403, replay_denied.text
    finally:
        await first.close()
        await second.close()
