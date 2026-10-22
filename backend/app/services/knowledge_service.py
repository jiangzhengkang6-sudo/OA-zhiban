"""
OA 智能体管理系统 - 知识库服务。

提供文档导入（切分 + 向量化 + 入库）与权限过滤检索。MVP 采用简单段落切分，
embedding 通过 EmbeddingClient 抽象（Mock 确定性 / ARK 真实）。
"""

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.base import LLMFactory
from ..repositories import knowledge_repo
from .document_parser import parse_bytes
from ..storage.base import ObjectStore
from ..core.config import get_settings
from ..core.context import get_current_user

_CHUNK_SIZE = 500  # 单切片字符上限
_SENTENCE_BOUNDARY = re.compile(
    r"(?<=[。！？!?])|(?<=[.!?])(?=\s+|$)|\n+"
)
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}(?:\s+|$)")


def preview_document(
    content: bytes, filename: str, *, store: ObjectStore | None = None
) -> dict:
    """Parse a source file and optionally persist its immutable raw bytes.

    The function is intentionally independent of the database so callers can show a
    preview before creating a knowledge version.
    """
    blocks = parse_bytes(content, filename)
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix == "markdown":
        suffix = "md"
    if suffix == "htm":
        suffix = "html"
    content_hash = hashlib.sha256(content).hexdigest()
    result = {
        "filename": Path(filename).name,
        "format": suffix,
        "content_hash": content_hash,
        "blocks": [
            {
                "text": block.text,
                "page": block.page,
                "section": block.section,
                "paragraph": block.paragraph,
            }
            for block in blocks
        ],
    }
    if store is not None:
        reference = f"knowledge/{content_hash}.{suffix}"
        result["file_reference"] = store.put(content, reference)
    return result


async def import_document(
    session: AsyncSession,
    *,
    title: str,
    content: str,
    format: str = "md",
    permission_tags: Optional[list[str]] = None,
    owner_id: str = "u_admin_001",
    effective_at: Optional[datetime] = None,
    expire_at: Optional[datetime] = None,
) -> dict:
    """导入文档：切分、向量化并入库。

    Args:
        session: 数据库会话。
        title: 文档标题。
        content: 文档正文。
        format: 源格式。
        permission_tags: 权限标签。
        owner_id: 责任人。
        effective_at: 生效时间。
        expire_at: 失效时间。

    Returns:
        dict: 导入结果（document_id / chunk_count）。
    """
    permission_tags = permission_tags or []
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    doc = await knowledge_repo.add_document(
        session,
        title=title,
        format=format,
        permission_tags=permission_tags,
        owner_id=owner_id,
        content_hash=content_hash,
        status="published",
        effective_at=effective_at,
        expire_at=expire_at,
    )

    chunks = _split_chunks(content)
    embedder = LLMFactory.get_embedding()
    vectors = await embedder.embed(chunks)

    for idx, (text, vec) in enumerate(zip(chunks, vectors)):
        await knowledge_repo.add_chunk(
            session,
            document_id=doc.id,
            chunk_index=idx,
            content=text,
            embedding=vec,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            source_location=f"{title}#chunk-{idx}",
            token_count=len(text) // 2,
        )
    await session.commit()
    return {"document_id": str(doc.id), "chunk_count": len(chunks)}


async def search(
    session: AsyncSession,
    *,
    query: str,
    permission_tags: list[str],
    top_k: int = 5,
) -> list[dict]:
    """权限过滤知识检索。

    Args:
        session: 数据库会话。
        query: 用户问题。
        permission_tags: 用户可访问的权限标签。
        top_k: 返回条数。

    Returns:
        list[dict]: 命中切片（含来源定位与相似度）。
    """
    actor = get_current_user() if get_settings().oa_provider == "builtin" else None
    if get_settings().oa_provider == 'builtin':
        from .authorization_service import require_fresh_identity, require_permission
        actor = await require_fresh_identity(actor, session=session)
        require_permission(actor, 'knowledge', 'read')
        permission_tags = actor.depts
    embedder = LLMFactory.get_embedding()
    vectors = await embedder.embed([query])
    if actor is not None:
        actor = await require_fresh_identity(actor, session=session)
        require_permission(actor, 'knowledge', 'read')
        permission_tags = actor.depts
    versioned = await knowledge_repo.search_version_chunks(
        session,
        query_vector=vectors[0],
        permission_tags=permission_tags,
        top_k=top_k,
        actor=actor,
    )
    if versioned:
        return versioned
    # Formal builtin knowledge is source-bound.  An empty current result must
    # never expose legacy knowledge_chunk rows that lack tenant ownership.
    if get_settings().oa_provider == "builtin":
        return []
    return await knowledge_repo.search_chunks(
        session,
        query_vector=vectors[0],
        permission_tags=permission_tags,
        top_k=top_k,
    )


def _split_chunks(content: str) -> list[str]:
    """按文档结构分段，再按句子切分并控制长度。

    Args:
        content: 文档正文。

    Returns:
        list[str]: 切片列表。
    """
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        # 保留原有行为：空文档仍然产生一个可写入的切片。
        return [content]

    # 空行是段落边界，Markdown 标题单独成为语义单元，避免与上一段粘连。
    units: list[str] = []
    for block in re.split(r"\n\s*\n+", normalized):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        current: list[str] = []
        for line in lines:
            if _MARKDOWN_HEADING.match(line):
                if current:
                    units.extend(_sentence_units("\n".join(current)))
                    current = []
                units.append(line)
            else:
                current.append(line)
        if current:
            units.extend(_sentence_units("\n".join(current)))

    chunks: list[str] = []
    buf = ""
    for unit in units:
        if len(unit) > _CHUNK_SIZE:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(
                unit[start : start + _CHUNK_SIZE]
                for start in range(0, len(unit), _CHUNK_SIZE)
            )
        elif not buf:
            buf = unit
        elif len(buf) + 1 + len(unit) <= _CHUNK_SIZE:
            buf = f"{buf}\n{unit}"
        else:
            chunks.append(buf)
            buf = unit
    if buf:
        chunks.append(buf)
    return chunks


def _sentence_units(text: str) -> list[str]:
    """Split text on Chinese/English sentence punctuation and line breaks."""

    return [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]
