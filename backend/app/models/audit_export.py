"""Controlled audit export metadata."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class AuditExport(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "audit_export"
    __table_args__ = (Index("ix_audit_export_requested_by_created", "requested_by", "created_at"),)

    requested_by: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    storage_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
