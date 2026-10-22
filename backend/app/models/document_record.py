"""Owned document drafting record and immutable input snapshots."""
from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class DocumentRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "document_record"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_document_record_document_id"),
        UniqueConstraint("tenant_id", "owner_id", "idempotency_key", name="uq_document_record_create_idempotency"),
        Index("ix_document_record_owner_status", "tenant_id", "owner_id", "status"),
    )

    document_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_thread.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    template_id: Mapped[str] = mapped_column(String(32), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    template_sections: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    input_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient: Mapped[str] = mapped_column(String(500), nullable=False)
    deadline: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    classification: Mapped[str] = mapped_column(String(24), nullable=False, default="internal")
    distribution: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CREATED")
    current_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    error_trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confirmation: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
