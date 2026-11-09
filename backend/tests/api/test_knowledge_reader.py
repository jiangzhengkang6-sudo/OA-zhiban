"""Published source reading must enforce the same boundary as FAQ retrieval."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.core.errors import AppException
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_source import KnowledgeSource
from app.models.knowledge_version import KnowledgeVersion
from app.models.oa_ai_scope import OAKnowledgeBinding
from app.services import knowledge_reader_service as reader
from tests.oa_support import oa_db, seed


async def material(db, actor, *, status='published', **overrides):
    source = KnowledgeSource(tenant_id=actor.tenant_id, name='公开参考材料', owner_id=actor.user_id)
    db.add(source)
    await db.flush()
    version = KnowledgeVersion(source_id=source.id, version=1, status=status,
        parse_status='READY', permission_tags=actor.depts, **overrides)
    db.add(version)
    await db.flush()
    db.add_all([
        OAKnowledgeBinding(tenant_id=actor.tenant_id, source_id=source.id,
            owner_id=actor.user_id, department_id=actor.depts[0], access_scope='department'),
        KnowledgeChunk(document_id=version.id, version_id=version.id, chunk_index=0,
            content='提交前请核对材料。', source_location='page=None;section=材料清单;paragraph=1'),
    ])
    await db.commit()
    return source, version


async def test_reader_lists_formal_versions_and_checks_source_version_pair(oa_db):
    async with oa_db() as db:
        actor = await seed(db, resources=['knowledge'])
        colleague = await seed(db, tenant=actor.tenant_id, department=actor.depts[0], resources=['knowledge'])
        other = await seed(db, tenant=actor.tenant_id, resources=['knowledge'])
        outsider = await seed(db, resources=['knowledge'])
        no_grant = await seed(db, tenant=actor.tenant_id, department=actor.depts[0])
        source, version = await material(db, actor)
        other_source, other_version = await material(db, outsider)
        rows = await reader.list_published(db, colleague)
        assert [row['source_id'] for row in rows] == [str(source.id)]
        detail = await reader.read_version(db, colleague, source.id, version.id)
        assert detail['version_id'] == str(version.id)
        assert detail['blocks'][0]['text'] == '提交前请核对材料。'
        assert 'embedding' not in detail['blocks'][0]
        for denied_actor, source_id, version_id in (
            (other, source.id, version.id), (outsider, source.id, version.id),
            (colleague, source.id, other_version.id), (colleague, other_source.id, version.id),
            (colleague, source.id, uuid4()),
        ):
            with pytest.raises(AppException) as error:
                await reader.read_version(db, denied_actor, source_id, version_id)
            assert error.value.http_status == 404
        assert await reader.list_published(db, other) == []
        with pytest.raises(AppException) as error:
            await reader.list_published(db, no_grant)
        assert error.value.http_status == 403


@pytest.mark.parametrize('change', ['draft', 'offline', 'expired', 'future', 'parse', 'tags', 'binding'])
async def test_reader_rechecks_publication_and_binding_on_old_links(oa_db, change):
    async with oa_db() as db:
        actor = await seed(db, resources=['knowledge'])
        source, version = await material(db, actor)
        assert (await reader.read_version(db, actor, source.id, version.id))['blocks']
        if change in {'draft', 'offline'}:
            version.status = change
        elif change == 'expired':
            version.expire_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        elif change == 'future':
            version.effective_at = datetime.now(timezone.utc) + timedelta(days=1)
        elif change == 'parse':
            version.parse_status = 'PENDING'
        elif change == 'tags':
            version.permission_tags = [str(uuid4())]
        else:
            from sqlalchemy import select
            binding = await db.scalar(select(OAKnowledgeBinding).where(OAKnowledgeBinding.source_id == source.id))
            binding.status = 'inactive'
        await db.commit()
        assert await reader.list_published(db, actor) == []
        with pytest.raises(AppException) as error:
            await reader.read_version(db, actor, source.id, version.id)
        assert error.value.http_status == 404
