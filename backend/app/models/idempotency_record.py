"""Durable idempotency ledger for every high-impact command."""
from typing import Optional
from uuid import UUID
from sqlalchemy import CheckConstraint, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, TimestampMixin, UUIDMixin


class IdempotencyRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "idempotency_record"
    __table_args__ = (
        UniqueConstraint("tenant_id", "actor_id", "resource_type", "resource_id", "idempotency_key", name="uq_idempotency_scope"),
        CheckConstraint("status IN ('PENDING','SUCCEEDED','FAILED','UNKNOWN')", name="ck_idempotency_record_valid_status"),
        Index("ix_idempotency_record_status_created", "status", "created_at"),
    )

    command_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    external_request_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
