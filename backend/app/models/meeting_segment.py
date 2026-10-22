"""Ordered source segments used for citations."""

from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class MeetingSegment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "meeting_segment"
    __table_args__ = (
        UniqueConstraint("meeting_id", "ordinal", name="uq_meeting_segment_ordinal"),
        Index("ix_meeting_segment_source_order", "source_id", "ordinal"),
    )

    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meeting_record.id"), nullable=False)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("meeting_source.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    locator: Mapped[dict] = mapped_column(JSONB, nullable=False)
    summary: Mapped[str] = mapped_column(String(256), nullable=False)

