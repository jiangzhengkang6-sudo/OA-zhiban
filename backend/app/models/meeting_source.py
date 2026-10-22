"""Protected meeting source metadata; raw content is addressed indirectly."""

from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class MeetingSource(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "meeting_source"
    __table_args__ = (Index("ix_meeting_source_meeting_created", "meeting_id", "created_at"),)

    meeting_id: Mapped[UUID] = mapped_column(ForeignKey("meeting_record.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    content_length: Mapped[int] = mapped_column(Integer, nullable=False)

