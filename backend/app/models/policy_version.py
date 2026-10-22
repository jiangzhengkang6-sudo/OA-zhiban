"""Immutable published policy snapshots."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class PolicyVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "policy_version"
    __table_args__ = (
        Index("ix_policy_version_scope_status", "scene", "scope_type", "scope_value", "status"),
    )

    scene: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    scope_value: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
