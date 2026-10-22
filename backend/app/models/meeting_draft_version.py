"""Immutable structured meeting draft versions."""

from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class MeetingDraftVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "meeting_draft_version"
    __table_args__ = (
        UniqueConstraint("meeting_id", "version", name="uq_meeting_draft_version_number"),
        Index("ix_meeting_draft_version_meeting_status", "meeting_id", "status"),
    )

    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meeting_record.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT_READY")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    topics: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    decisions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    action_items: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    edited_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

