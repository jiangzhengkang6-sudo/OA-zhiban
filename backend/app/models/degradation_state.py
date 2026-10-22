"""Persisted administrator-controlled degradation switches."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class DegradationState(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "degradation_state"
    __table_args__ = (
        Index("ix_degradation_state_lookup", "scene", "scope_type", "scope_value", "enabled"),
    )

    scene: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    scope_value: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    new_task_action: Mapped[str] = mapped_column(String(16), nullable=False, default="fallback")
    inflight_action: Mapped[str] = mapped_column(String(16), nullable=False, default="continue")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    restored_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    restored_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
