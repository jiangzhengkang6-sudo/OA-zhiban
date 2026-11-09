"""Public-corpus import preserves tenant authority, exact bytes and idempotence."""
import pytest
from sqlalchemy import func, select

from app.core.context import set_current_user
from app.models.knowledge_source import KnowledgeSource
from app.models.knowledge_version import KnowledgeVersion
from app.models.oa_ai_scope import OABusinessAudit
from app.services import knowledge_service, oa_scope_service
from app.storage.local import LocalObjectStore
from scripts import import_public_company_knowledge as importer
from tests.oa_support import oa_db, seed


async def test_import_is_published_idempotent_and_tenant_scoped(oa_db, tmp_path):
    manifest, documents = importer.load_corpus()
    documents = documents[:1]
    receipt = {'checked_at': '2026-10-22T12:00:00Z'}
    async with oa_db() as db:
        actor = await seed(db, resources=['knowledge'])
        outsider = await seed(db, resources=['knowledge'])
        colleague = await seed(db, tenant=actor.tenant_id, department=actor.depts[0], resources=['knowledge'])
        other_department = await seed(db, tenant=actor.tenant_id, resources=['knowledge'])
        await db.commit()
        set_current_user(actor)
        try:
            store = LocalObjectStore(tmp_path)
            first = await importer.import_documents(db, actor, documents, manifest, receipt, store)
            stored = await db.get(KnowledgeVersion, first[0]['version_id'])
            await db.refresh(stored)
            assert stored.permission_tags == actor.depts
            again = await importer.import_documents(db, actor, documents, manifest, receipt, store)
            assert first[0]['action'] == 'created' and again[0]['action'] == 'reused'
            assert first[0]['version_id'] == again[0]['version_id']
            assert first[0]['chunks'] == documents[0]['block_count']
            source = await db.scalar(select(KnowledgeSource).where(KnowledgeSource.tenant_id == actor.tenant_id))
            version = await db.scalar(select(KnowledgeVersion).where(KnowledgeVersion.source_id == source.id))
            assert version.status == 'published'
            assert await oa_scope_service.source_allowed(db, actor, source.id, version_id=version.id)
            assert await oa_scope_service.source_allowed(db, colleague, source.id, version_id=version.id)
            assert not await oa_scope_service.source_allowed(db, other_department, source.id, version_id=version.id)
            assert not await oa_scope_service.source_allowed(db, outsider, source.id, version_id=version.id)
            assert await db.scalar(select(func.count()).select_from(OABusinessAudit).where(
                OABusinessAudit.tenant_id == actor.tenant_id, OABusinessAudit.action == 'knowledge.imported')) == 1
            other = await importer.import_documents(db, outsider, documents, manifest, receipt, store)
            assert other[0]['source_id'] != first[0]['source_id']
        finally:
            set_current_user(None)


async def test_import_conflict_does_not_replace_existing_policy(oa_db, tmp_path):
    manifest, documents = importer.load_corpus()
    documents = documents[:1]
    receipt = {'checked_at': '2026-10-22T12:00:00Z'}
    async with oa_db() as db:
        actor = await seed(db, resources=['knowledge'])
        await db.commit()
        store = LocalObjectStore(tmp_path)
        await importer.import_documents(db, actor, documents, manifest, receipt, store)
        changed = dict(documents[0], sha256='f' * 64)
        with pytest.raises(ValueError, match='existing_source_conflict'):
            await importer.import_documents(db, actor, [changed], manifest, receipt, store)
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(KnowledgeVersion).join(KnowledgeSource).where(
            KnowledgeSource.tenant_id == actor.tenant_id, KnowledgeVersion.status == 'published')) == 1
