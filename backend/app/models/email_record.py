"""Private mail source snapshot and review state."""
from uuid import UUID
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, TimestampMixin, UUIDMixin


class EmailRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "email_record"
    __table_args__ = (
        UniqueConstraint("email_id", name="uq_email_record_email_id"),
        UniqueConstraint("tenant_id", "owner_id", "idempotency_key", name="uq_email_record_create_idempotency"),
        Index("ix_email_record_owner_status", "tenant_id", "owner_id", "status"),
    )
    email_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_thread.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CREATED")
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    confirmation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
