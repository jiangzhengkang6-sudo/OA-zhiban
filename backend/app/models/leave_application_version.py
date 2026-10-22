"""Immutable built-in leave form versions."""

from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class LeaveApplicationVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "leave_application_version"
    __table_args__ = (UniqueConstraint("application_id", "version", name="uq_leave_application_version"),
                      Index("ix_leave_application_version_application", "application_id", "version"))

    application_id: Mapped[UUID] = mapped_column(ForeignKey("leave_application.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False)
    precheck_result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
