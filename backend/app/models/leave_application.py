"""Built-in leave application aggregate."""

from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class LeaveApplication(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "leave_application"
    __table_args__ = (
        Index("ix_leave_application_owner_status", "tenant_id", "user_id", "status"),
        Index("uq_leave_application_thread_id", "thread_id", unique=True,
              postgresql_where=text("thread_id IS NOT NULL")),
    )

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("agent_thread.id"), nullable=True)
    business_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rule_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    latest_fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
