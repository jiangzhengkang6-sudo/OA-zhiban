"""Auditable human decisions for meeting drafts."""

from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class MeetingDecision(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "meeting_decision"
    __table_args__ = (
        UniqueConstraint("meeting_id", "idempotency_key", name="uq_meeting_decision_idempotency"),
        Index("ix_meeting_decision_meeting_created", "meeting_id", "created_at"),
    )

    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meeting_record.id"), nullable=False)
    draft_version_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("meeting_draft_version.id"), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)

