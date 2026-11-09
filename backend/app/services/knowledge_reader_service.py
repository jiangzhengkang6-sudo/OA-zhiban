"""Read published evidence with the same live scope and window as retrieval."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from ..core.errors import not_found
from ..models.knowledge_chunk import KnowledgeChunk
from ..models.knowledge_source import KnowledgeSource
from ..models.knowledge_version import KnowledgeVersion
from .authorization_service import require_fresh_identity, require_permission
from .oa_scope_service import knowledge_binding_clause


async def visible_versions(db, actor):
    actor = await require_fresh_identity(actor, session=db)
    require_permission(actor, 'knowledge', 'read')
    now = datetime.now(timezone.utc)
    tags = KnowledgeVersion.permission_tags == []
    if actor.depts:
        tags = tags | KnowledgeVersion.permission_tags.overlap(actor.depts)
    return select(KnowledgeSource, KnowledgeVersion).join(
        KnowledgeVersion, KnowledgeVersion.source_id == KnowledgeSource.id
    ).where(
        KnowledgeSource.tenant_id == actor.tenant_id,
        KnowledgeVersion.status == 'published', KnowledgeVersion.parse_status == 'READY',
        (KnowledgeVersion.effective_at.is_(None)) | (KnowledgeVersion.effective_at <= now),
        (KnowledgeVersion.expire_at.is_(None)) | (KnowledgeVersion.expire_at > now),
        tags, knowledge_binding_clause(actor),
    ).execution_options(populate_existing=True)


def metadata(source, version):
    return dict(source_id=str(source.id), version_id=str(version.id), title=source.name,
        version=version.version, status=version.status, effective_at=version.effective_at,
        expire_at=version.expire_at)


async def list_published(db, actor):
    query = await visible_versions(db, actor)
    rows = (await db.execute(query.order_by(KnowledgeSource.name, KnowledgeVersion.version.desc()))).all()
    return [metadata(source, version) for source, version in rows]


async def read_version(db, actor, source_id: UUID, version_id: UUID):
    query = (await visible_versions(db, actor)).where(
        KnowledgeSource.id == source_id, KnowledgeVersion.id == version_id)
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise not_found('资料不存在、已失效或无权查看')
    chunks = (await db.scalars(select(KnowledgeChunk).where(
        KnowledgeChunk.version_id == version_id).order_by(KnowledgeChunk.chunk_index))).all()
    return dict(**metadata(*row), blocks=[dict(id=str(chunk.id), text=chunk.content,
        source_location=chunk.source_location or '') for chunk in chunks])
