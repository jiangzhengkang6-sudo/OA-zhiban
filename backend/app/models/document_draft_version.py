"""Immutable document draft revisions."""
from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class DocumentDraftVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "document_draft_version"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_document_draft_version_number"),
        Index("ix_document_draft_version_document_created", "document_id", "created_at"),
    )

    document_id: Mapped[UUID] = mapped_column(ForeignKey("document_record.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    checks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    edited_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
