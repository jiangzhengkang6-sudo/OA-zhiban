"""Original file metadata; bytes remain in ObjectStore."""

from typing import Optional
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class KnowledgeFile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "knowledge_file"
    __table_args__ = (Index("ix_knowledge_file_version", "version_id"),)

    version_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_version.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
