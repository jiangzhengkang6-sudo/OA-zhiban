"""Authoritative built-in ticket record."""

from typing import Optional

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class TicketRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "ticket_record"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_ticket_record_idempotency"),
        Index("ix_ticket_record_owner_status", "tenant_id", "user_id", "status"),
        Index("ix_ticket_record_queue_status", "tenant_id", "queue_id", "status"),
    )

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    thread_id: Mapped[Optional[object]] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    impact: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    queue_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    assignee_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    assignment_rule_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    assignment_error: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    merged_from: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
