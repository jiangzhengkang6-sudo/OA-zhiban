"""Owner-private confirmed report plans and platform publication records."""
from uuid import UUID
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, TimestampMixin, UUIDMixin


class ReportRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "report_record"
    __table_args__ = (
        UniqueConstraint("report_id", name="uq_report_record_report_id"),
        UniqueConstraint("tenant_id", "owner_id", "idempotency_key", name="uq_report_record_create_idempotency"),
        Index("ix_report_record_owner_status", "tenant_id", "owner_id", "status"),
    )
    report_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_thread.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[dict] = mapped_column(JSONB, nullable=False)
    scope_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PLAN_READY")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_confirmation: Mapped[dict | None] = mapped_column(JSONB)
    cached_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    publication: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(32))
    error_trace_id: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)


class ReportVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "report_version"
    __table_args__ = (UniqueConstraint("report_id", "version", name="uq_report_version_number"),)
    report_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("report_record.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    draft: Mapped[dict] = mapped_column(JSONB, nullable=False)
    edited_by: Mapped[str | None] = mapped_column(String(64))
