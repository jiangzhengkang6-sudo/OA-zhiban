"""Immutable mail analysis and reply revisions."""
from uuid import UUID
from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, TimestampMixin, UUIDMixin


class EmailDraftVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "email_draft_version"
    __table_args__ = (
        UniqueConstraint("email_id", "version", name="uq_email_draft_version_number"),
        Index("ix_email_draft_version_email_created", "email_id", "created_at"),
    )
    email_id: Mapped[UUID] = mapped_column(ForeignKey("email_record.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    draft: Mapped[dict] = mapped_column(JSONB, nullable=False)
    checks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    edited_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
