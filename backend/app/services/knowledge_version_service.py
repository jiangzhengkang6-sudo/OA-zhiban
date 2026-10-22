"""Database lifecycle for source-backed knowledge versions."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.base import LLMFactory
from ..models.knowledge_file import KnowledgeFile
from ..models.knowledge_source import KnowledgeSource
from ..models.knowledge_version import KnowledgeVersion
from ..models.knowledge_chunk import KnowledgeChunk
from ..services.document_parser import parse_bytes
from ..storage.base import ObjectStore
from .knowledge_service import _split_chunks


def next_version_number(existing_versions: list[int]) -> int:
    return max(existing_versions, default=0) + 1


def validate_publish_window(
    effective_at: datetime | None,
    expire_at: datetime | None,
    *,
    now: datetime | None = None,
) -> None:
    if effective_at and expire_at and expire_at <= effective_at:
        raise ValueError("expire_at must be after effective_at")
    current = now or datetime.now(timezone.utc)
    if expire_at and expire_at <= current:
        raise ValueError("version is already expired")


def build_version_metadata(
    *, content_hash: str, filename: str, size_bytes: int, content_type: str | None
) -> dict:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix == "markdown":
        suffix = "md"
    if suffix == "htm":
        suffix = "html"
    return {
        "status": "draft",
        "parse_status": "READY",
        "content_hash": content_hash,
        "filename": Path(filename).name,
        "size_bytes": size_bytes,
        "content_type": content_type,
        "format": suffix,
    }


async def create_version(
    session: AsyncSession,
    *,
    source_name: str,
    content: bytes,
    filename: str,
    permission_tags: list[str],
    owner_id: str,
    effective_at: datetime | None = None,
    expire_at: datetime | None = None,
    store: ObjectStore | None = None,
    content_type: str | None = None,
    tenant_id: str = "default",
) -> KnowledgeVersion:
    """Create a parsed draft version and its file/chunks; do not publish it."""
    validate_publish_window(effective_at, expire_at)
    blocks = parse_bytes(content, filename)
    digest = hashlib.sha256(content).hexdigest()
    source = (await session.execute(
        select(KnowledgeSource).where(
            KnowledgeSource.tenant_id == tenant_id, KnowledgeSource.name == source_name
        )
    )).scalar_one_or_none()
    if source is None:
        source = KnowledgeSource(tenant_id=tenant_id, name=source_name, owner_id=owner_id)
        session.add(source)
        await session.flush()
    versions = (await session.execute(
        select(KnowledgeVersion.version).where(KnowledgeVersion.source_id == source.id)
    )).scalars().all()
    version = KnowledgeVersion(
        source_id=source.id, version=next_version_number(list(versions)), status="draft",
        parse_status="READY", permission_tags=permission_tags, owner_id=owner_id,
        content_hash=digest, effective_at=effective_at, expire_at=expire_at,
    )
    session.add(version)
    await session.flush()
    reference = f"knowledge/{digest}{Path(filename).suffix.lower()}"
    if store is not None:
        reference = store.put(content, reference)
    session.add(KnowledgeFile(
        version_id=version.id, filename=Path(filename).name, storage_ref=reference,
        sha256=digest, size_bytes=len(content), content_type=content_type,
        format=Path(filename).suffix.lower().lstrip("."),
    ))
    chunk_texts = [block.text for block in blocks if block.text.strip()] or _split_chunks(content.decode("utf-8", errors="replace"))
    vectors = await LLMFactory.get_embedding().embed(chunk_texts)
    for index, (text, vector) in enumerate(zip(chunk_texts, vectors)):
        block = blocks[min(index, len(blocks) - 1)]
        session.add(KnowledgeChunk(
            document_id=version.id, version_id=version.id, chunk_index=index, content=text,
            embedding=vector, content_hash=hashlib.sha256(text.encode()).hexdigest(),
            source_location=f"page={block.page};section={block.section};paragraph={block.paragraph}",
            token_count=max(1, len(text) // 2),
        ))
    await session.flush()
    return version


async def publish_version(
    session: AsyncSession, version_id: UUID, *, now: datetime | None = None
) -> KnowledgeVersion:
    version = await session.get(KnowledgeVersion, version_id)
    if version is None:
        raise ValueError("knowledge version not found")
    if version.parse_status != "READY":
        raise ValueError("version is not ready")
    validate_publish_window(version.effective_at, version.expire_at, now=now)
    await session.execute(
        update(KnowledgeVersion)
        .where(
            KnowledgeVersion.source_id == version.source_id,
            KnowledgeVersion.status == "published",
            KnowledgeVersion.id != version.id,
        )
        .values(status="offline")
    )
    version.status = "published"
    await session.flush()
    return version
