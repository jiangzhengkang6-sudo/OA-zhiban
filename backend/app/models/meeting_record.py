"""Meeting task metadata and tenant ownership."""

from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class MeetingRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "meeting_record"
    __table_args__ = (
        UniqueConstraint("meeting_id", name="uq_meeting_record_meeting_id"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_meeting_record_tenant_idempotency"),
        Index("ix_meeting_record_tenant_status", "tenant_id", "status"),
        Index("ix_meeting_record_owner_created", "owner_id", "created_at"),
    )

    meeting_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_thread.id"), nullable=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CREATED")
    current_version: Mapped[Optional[int]] = mapped_column(nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    error_trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

