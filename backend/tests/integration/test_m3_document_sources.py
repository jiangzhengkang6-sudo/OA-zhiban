"""Formal document knowledge is filtered before ranking and rechecked on reuse."""
from hashlib import sha256
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core import config
from app.core.context import get_current_user, set_current_user
from app.core.errors import AppException
from app.llm.base import LLMFactory
from app.models.document_record import DocumentRecord
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_source import KnowledgeSource
from app.models.knowledge_version import KnowledgeVersion
from app.models.oa_ai_scope import OAKnowledgeBinding
from app.providers import identity
from app.schemas.document import DocumentInput, DocumentCommand
from app.services import document_service, document_generator, oa_scope_service, policy_service, thread_service
from tests.integration.test_m3_formal_sources import revoke
from tests.oa_support import oa_db, seed


@pytest.fixture
def formal_documents(oa_db, monkeypatch):
    settings = policy_service.get_settings()
    monkeypatch.setattr(settings, 'oa_provider', 'builtin')
    monkeypatch.setattr(settings, 'auth_provider', 'builtin')
    monkeypatch.setattr(config, 'get_settings', lambda: settings)
    monkeypatch.setattr(identity, 'get_settings', lambda: settings)
    previous = get_current_user()
    yield oa_db
    set_current_user(previous)


def payload(key='source-document'):
    return DocumentInput(template_id='notice', subject='项目通知', recipient='项目组',
        key_points='完成验收材料', distribution='项目组内部', use_knowledge=True, idempotency_key=key)


async def source(db, actor, *, bound=True, owner=None, vector=None):
    text = '已发布的正式项目制度'
    row = KnowledgeSource(tenant_id=actor.tenant_id, name='项目制度', owner_id=actor.user_id)
    db.add(row)
    await db.flush()
    version = KnowledgeVersion(source_id=row.id, version=1, status='published', parse_status='READY', permission_tags=[])
    db.add(version)
    await db.flush()
    chunk = KnowledgeChunk(document_id=row.id, version_id=version.id, content=text,
        content_hash=sha256(text.encode()).hexdigest(), embedding=vector or (await LLMFactory.get_embedding().embed([text]))[0])
    db.add(chunk)
    binding = None
    if bound:
        binding = await oa_scope_service.create_binding(db, actor=actor, source_id=row.id,
            owner_id=owner or actor.user_id, department_id=actor.depts[0], access_scope='owner')
    await db.flush()
    return chunk, binding


async def setup(db):
    actor = await seed(db, resources=['document', 'knowledge', 'thread'], scope='self')
    chunk, binding = await source(db, actor)
    await db.commit()
    set_current_user(actor)
    return actor, chunk, binding


async def test_formal_document_filters_bindings_before_vector_ranking(formal_documents):
    async with formal_documents() as db:
        actor, allowed, _ = await setup(db)
        query = payload().subject + ' ' + payload().key_points
        exact = (await LLMFactory.get_embedding().embed([query]))[0]
        for index in range(7):
            await source(db, actor, bound=index != 0, owner='another-user', vector=exact)
        await db.commit()
        result = await document_service.create_document(db, actor, payload())
        knowledge = [item for item in result.sources if item.kind == 'knowledge']
        assert [item.ref for item in knowledge] == [f'knowledge:{allowed.id}']


async def test_formal_document_requires_knowledge_read_before_embedding(formal_documents, monkeypatch):
    async with formal_documents() as db:
        actor, _, _ = await setup(db)
        await revoke(db, actor, 'knowledge')
        monkeypatch.setattr(LLMFactory, 'get_embedding', lambda: pytest.fail('denied document reached embedding'))
        with pytest.raises(AppException) as denied:
            await document_service.create_document(db, actor, payload())
        assert denied.value.http_status == 403


@pytest.mark.parametrize('entry', ['detail', 'versions', 'create_replay', 'generate_replay', 'thread'])
async def test_formal_document_rechecks_revoked_binding_on_derived_reads(formal_documents, entry):
    async with formal_documents() as db:
        actor, _, binding = await setup(db)
        created = await document_service.create_document(db, actor, payload())
        command = DocumentCommand(idempotency_key='source-generate')
        await document_service.generate_draft(db, actor, created.document_id, command)
        await db.commit()
        async with formal_documents() as mutation:
            row = await mutation.get(OAKnowledgeBinding, binding.id)
            row.status = 'revoked'
            await mutation.commit()
        if entry == 'thread':
            from app.models.agent_thread import AgentThread
            thread = await db.get(AgentThread, UUID(created.thread_id))
            assert not await thread_service.can_view_thread(thread, actor, db)
            return
        with pytest.raises(AppException) as denied:
            if entry == 'detail':
                await document_service.get_document(db, actor, created.document_id)
            elif entry == 'versions':
                await document_service.list_versions(db, actor, created.document_id)
            elif entry == 'create_replay':
                await document_service.create_document(db, actor, payload())
            else:
                await document_service.generate_draft(db, actor, created.document_id, command)
        assert denied.value.http_status == 403


async def test_formal_document_discards_generation_when_binding_scope_changes(formal_documents, monkeypatch):
    async with formal_documents() as db:
        actor, _, binding = await setup(db)
        created = await document_service.create_document(db, actor, payload())
        async def generate(data, template, sources):
            async with formal_documents() as mutation:
                row = await mutation.get(OAKnowledgeBinding, binding.id)
                row.owner_id = 'new-owner'
                await mutation.commit()
            return document_generator.generate_document_draft(data, template, sources)
        monkeypatch.setattr(document_generator, 'generate', generate)
        with pytest.raises(AppException) as denied:
            await document_service.generate_draft(db, actor, created.document_id, DocumentCommand(idempotency_key='changed-source'))
        assert denied.value.http_status == 403


async def test_formal_document_rejects_tampered_source_snapshot_before_model(formal_documents, monkeypatch):
    async with formal_documents() as db:
        actor, _, _ = await setup(db)
        created = await document_service.create_document(db, actor, payload())
        record = await db.scalar(select(DocumentRecord).where(DocumentRecord.document_id == created.document_id))
        record.source_snapshot = [{**item, 'content': '伪造正文'} if item['kind'] == 'knowledge' else item
            for item in record.source_snapshot]
        await db.commit()
        monkeypatch.setattr(document_generator, 'generate', lambda *args: pytest.fail('tampered evidence reached model'))
        with pytest.raises(AppException) as denied:
            await document_service.generate_draft(db, actor, created.document_id, DocumentCommand(idempotency_key='tampered-source'))
        assert denied.value.http_status == 403
