"""Exactly one active approver in an ordered approval instance."""
from datetime import datetime
from typing import Optional
from uuid import UUID
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, TimestampMixin, UUIDMixin


class ApprovalNode(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "approval_node"
    __table_args__ = (UniqueConstraint("instance_id", "node_order", name="uq_approval_node_order"),
                      Index("uq_approval_node_one_active", "instance_id", unique=True,
                            postgresql_where=text("status = 'ACTIVE'")),
                      Index("ix_approval_node_actor_status", "approver_id", "status"))

    instance_id: Mapped[UUID] = mapped_column(ForeignKey("approval_instance.id"), nullable=False)
    node_order: Mapped[int] = mapped_column(Integer, nullable=False)
    approver_id: Mapped[str] = mapped_column(String(64), nullable=False)
    approver_name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_proxy: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    waiting_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_nudge_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
