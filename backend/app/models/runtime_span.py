"""Tenant-scoped runtime event for future trace and metric drilldown."""
from datetime import datetime
from typing import Optional
from uuid import UUID
from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, TimestampMixin, UUIDMixin


class RuntimeSpan(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "runtime_span"
    __table_args__ = (Index("ix_runtime_span_tenant_trace", "tenant_id", "trace_id"),)

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[UUID] = mapped_column(nullable=False)
    thread_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
