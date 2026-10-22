"""
OA 智能体管理系统 - 知识库数据访问层。

提供知识文档与切片的写入、状态管理与向量检索（pgvector 余弦距离），检索时先按文档
状态/生效期/权限过滤，再取 top-k。
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.knowledge_chunk import KnowledgeChunk
from ..models.knowledge_document import KnowledgeDocument
from ..models.knowledge_version import KnowledgeVersion
from ..models.knowledge_source import KnowledgeSource
from ..models.oa_ai_scope import OAKnowledgeBinding


def _legacy_time(value: Optional[datetime]) -> Optional[datetime]:
    # Legacy document columns store UTC without timezone metadata.
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


async def add_document(
    session: AsyncSession,
    *,
    title: str,
    format: str,
    permission_tags: list[str],
    owner_id: str,
    content_hash: str,
    source_path: Optional[str] = None,
    status: str = "published",
    effective_at: Optional[datetime] = None,
    expire_at: Optional[datetime] = None,
) -> KnowledgeDocument:
    """新建知识文档。

    Args:
        session: 数据库会话。
        title: 文档标题。
        format: 源格式。
        permission_tags: 权限标签。
        owner_id: 责任人。
        content_hash: 内容哈希。
        source_path: 源路径。
        status: 状态。
        effective_at: 生效时间。
        expire_at: 失效时间。

    Returns:
        KnowledgeDocument: 新建文档记录。
    """
    doc = KnowledgeDocument(
        title=title, format=format, permission_tags=permission_tags,
        owner_id=owner_id, content_hash=content_hash, source_path=source_path,
        status=status, effective_at=_legacy_time(effective_at),
        expire_at=_legacy_time(expire_at), version=1,
    )
    session.add(doc)
    await session.flush()
    return doc


async def add_chunk(
    session: AsyncSession,
    *,
    document_id: UUID,
    chunk_index: int,
    content: str,
    embedding: Optional[list[float]],
    content_hash: str,
    source_location: str,
    token_count: int,
) -> KnowledgeChunk:
    """写入一条知识切片。

    Args:
        session: 数据库会话。
        document_id: 所属文档。
        chunk_index: 切片序号。
        content: 切片正文。
        embedding: 向量。
        content_hash: 内容哈希。
        source_location: 来源定位。
        token_count: 分词数。

    Returns:
        KnowledgeChunk: 写入的切片记录。
    """
    chunk = KnowledgeChunk(
        document_id=document_id, chunk_index=chunk_index, content=content,
        embedding=embedding, content_hash=content_hash,
        source_location=source_location, token_count=token_count,
    )
    session.add(chunk)
    await session.flush()
    return chunk


async def list_documents(
    session: AsyncSession, status: Optional[str] = None
) -> list[KnowledgeDocument]:
    """列出知识文档（可按状态过滤）。

    Args:
        session: 数据库会话。
        status: 状态过滤。

    Returns:
        list[KnowledgeDocument]: 文档列表。
    """
    stmt = select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())
    if status:
        stmt = stmt.where(KnowledgeDocument.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_document(
    session: AsyncSession, document_id: UUID
) -> Optional[KnowledgeDocument]:
    """按 ID 查询文档。

    Args:
        session: 数据库会话。
        document_id: 文档 ID。

    Returns:
        Optional[KnowledgeDocument]: 文档，无则 None。
    """
    return await session.get(KnowledgeDocument, document_id)


async def search_chunks(
    session: AsyncSession,
    *,
    query_vector: list[float],
    permission_tags: list[str],
    top_k: int = 5,
) -> list[dict]:
    """权限过滤 + 向量相似度检索 top-k 切片。

    仅检索 published 且处于生效期、且权限标签与用户可访问标签有交集的文档。

    Args:
        session: 数据库会话。
        query_vector: 查询向量。
        permission_tags: 用户可访问的权限标签集合。
        top_k: 返回条数。

    Returns:
        list[dict]: 命中切片列表（含内容/来源/相似度/文档标题）。
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    conds = [
        KnowledgeDocument.status == "published",
        # 生效期过滤（未设置视为始终生效）
        (KnowledgeDocument.effective_at.is_(None))
        | (KnowledgeDocument.effective_at <= now),
        (KnowledgeDocument.expire_at.is_(None))
        | (KnowledgeDocument.expire_at > now),
    ]
    # 权限过滤：文档公开（空标签）或与用户标签有交集
    if permission_tags:
        conds.append(
            (KnowledgeDocument.permission_tags == [])
            | KnowledgeDocument.permission_tags.overlap(permission_tags)
        )
    else:
        conds.append(KnowledgeDocument.permission_tags == [])

    distance = KnowledgeChunk.embedding.cosine_distance(query_vector).label("distance")
    stmt = (
        select(
            KnowledgeChunk,
            KnowledgeDocument.title,
            distance,
        )
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .where(*conds)
        .order_by(distance)
        .limit(top_k)
    )
    result = await session.execute(stmt)
    rows = result.all()
    out = []
    for chunk, title, dist in rows:
        similarity = 1.0 - float(dist)
        out.append(
            {
                "chunk_id": str(chunk.id),
                "document_id": str(chunk.document_id),
                "title": title,
                "content": chunk.content,
                "source_location": chunk.source_location or "",
                "similarity": round(max(similarity, 0.0), 4),
            }
        )
    return out


async def search_version_chunks(
    session: AsyncSession,
    *,
    query_vector: list[float],
    permission_tags: list[str],
    top_k: int = 5,
    actor=None,
) -> list[dict]:
    """Search only current, published source-backed version chunks."""
    now = datetime.now(timezone.utc)
    conds = [
        KnowledgeVersion.status == "published",
        (KnowledgeVersion.effective_at.is_(None)) | (KnowledgeVersion.effective_at <= now),
        (KnowledgeVersion.expire_at.is_(None)) | (KnowledgeVersion.expire_at > now),
    ]
    if permission_tags:
        conds.append(
            (KnowledgeVersion.permission_tags == [])
            | KnowledgeVersion.permission_tags.overlap(permission_tags)
        )
    else:
        conds.append(KnowledgeVersion.permission_tags == [])
    distance = KnowledgeChunk.embedding.cosine_distance(query_vector).label("distance")
    stmt = (
        select(KnowledgeChunk, KnowledgeVersion, distance)
        .join(KnowledgeVersion, KnowledgeChunk.version_id == KnowledgeVersion.id)
        .where(*conds)
        .order_by(distance)
        .limit(top_k)
    )
    if actor is not None:
        from ..services.oa_scope_service import knowledge_binding_clause
        # Formal builtin retrieval is tenant and binding scoped before vector
        # ranking. Legacy source rows without a binding stay invisible.
        stmt = stmt.join(KnowledgeSource, KnowledgeSource.id == KnowledgeVersion.source_id)
        stmt = stmt.where(
            KnowledgeSource.tenant_id == actor.tenant_id,
            KnowledgeVersion.parse_status == 'READY',
            knowledge_binding_clause(actor),
        )
    rows = (await session.execute(stmt)).all()
    result = []
    for chunk, version, dist in rows:
        result.append({
            "chunk_id": str(chunk.id),
            "version_id": str(version.id),
            "source_id": str(version.source_id),
            "version": version.version,
            "content": chunk.content,
            "source_location": chunk.source_location or "",
            "similarity": round(max(1.0 - float(dist), 0.0), 4),
        })
    return result
