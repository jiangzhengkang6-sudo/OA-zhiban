"""Immutable-ish version metadata for a knowledge source."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class KnowledgeVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "knowledge_version"
    __table_args__ = (
        Index("ix_knowledge_version_source_status", "source_id", "status"),
        Index("ix_knowledge_version_effective", "status", "effective_at", "expire_at"),
    )

    source_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_source.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    permission_tags: Mapped[list] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    owner_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    effective_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expire_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
