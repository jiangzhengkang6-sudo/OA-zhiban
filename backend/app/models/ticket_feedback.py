"""Idempotent user feedback for resolved support tickets."""

from sqlalchemy import Boolean, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class TicketFeedback(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "ticket_feedback"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_ticket_feedback_idempotency"),
        Index("ix_ticket_feedback_ticket", "tenant_id", "ticket_id"),
    )

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[object | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
