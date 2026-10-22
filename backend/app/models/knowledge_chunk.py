"""
OA 智能体管理系统 - 知识切片/向量表（knowledge_chunk）。

文档切分为若干 chunk，存储内容与向量（pgvector），并记录段落位置供来源定位。
检索 SQL 固定使用余弦距离（<=>）并先 JOIN knowledge_document 过滤权限与生效期。
"""

from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..core.config import get_settings
from ..db.base import Base, TimestampMixin, UUIDMixin

_settings = get_settings()


class KnowledgeChunk(Base, UUIDMixin, TimestampMixin):
    """知识切片。

    Attributes:
        document_id: 所属文档 ID（级联删除）。
        chunk_index: 切片序号。
        content: 切片正文。
        content_hash: 切片内容哈希。
        embedding: 向量（pgvector，维度由配置决定）。
        source_location: 来源定位（段落/页码）。
        token_count: 分词数。
    """

    __tablename__ = "knowledge_chunk"
    __table_args__ = (
        Index("ix_knowledge_chunk_doc", "document_id", "chunk_index"),
        Index("ix_knowledge_chunk_version", "version_id", "chunk_index"),
    )

    document_id: Mapped[object] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_id: Mapped[object | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_version.id"), nullable=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    embedding: Mapped[Optional[list]] = mapped_column(
        Vector(_settings.embedding_dim), nullable=True
    )
    source_location: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
