"""Immutable node-scoped human decision and exact replay result."""
from typing import Optional
from uuid import UUID
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, TimestampMixin, UUIDMixin


class ApprovalDecision(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "approval_decision"
    __table_args__ = (UniqueConstraint("instance_id", "idempotency_key", name="uq_approval_decision_command"),)

    instance_id: Mapped[UUID] = mapped_column(ForeignKey("approval_instance.id"), nullable=False)
    node_id: Mapped[UUID] = mapped_column(ForeignKey("approval_node.id"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    edited_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    result_status: Mapped[str] = mapped_column(String(32), nullable=False)
