"""One immutable ordered approval route for a leave application version."""
from typing import Optional
from uuid import UUID
from sqlalchemy import Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, TimestampMixin, UUIDMixin


class ApprovalInstance(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "approval_instance"
    __table_args__ = (UniqueConstraint("thread_id", "version", name="uq_approval_thread_version"),
                      Index("ix_approval_instance_tenant_status", "tenant_id", "status"))

    thread_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    business_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    route_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    external_request_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
