"""
OA 智能体管理系统 - 知识文档表（knowledge_document）。

企业知识文档治理：每条文档有版本、状态、权限标签、生效期与责任人，检索前必须按
权限标签 + 生效期过滤，过期/下线文档不可被检索。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import ARRAY

from ..db.base import Base, TimestampMixin, UUIDMixin


class KnowledgeDocument(Base, UUIDMixin, TimestampMixin):
    """知识文档。

    Attributes:
        title: 文档标题。
        version: 版本号。
        status: 状态（draft/published/expired/offline）。
        format: 源格式（md/html/pdf）。
        permission_tags: 权限标签数组（GIN 索引，检索权限过滤）。
        effective_at: 生效时间。
        expire_at: 失效时间。
        owner_id: 责任人 ID。
        content_hash: 文档内容哈希。
        source_path: 源文件路径。
        created_by: 创建人。
    """

    __tablename__ = "knowledge_document"
    __table_args__ = (
        Index("ix_knowledge_doc_status", "status", "effective_at", "expire_at"),
        Index("ix_knowledge_doc_permission", "permission_tags", postgresql_using="gin"),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="md")
    permission_tags: Mapped[list] = mapped_column(
        ARRAY(String(32)), nullable=False, default=list
    )
    effective_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    expire_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    owner_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)