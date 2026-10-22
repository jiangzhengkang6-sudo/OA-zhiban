"""Versioned built-in ticket assignment rules."""

from sqlalchemy import Boolean, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class TicketAssignmentRule(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "ticket_assignment_rule"
    __table_args__ = (
        UniqueConstraint("tenant_id", "rule_version", "category", "impact", name="uq_ticket_assignment_rule_version"),
        Index("ix_ticket_assignment_rule_lookup", "tenant_id", "enabled", "category", "impact", "priority"),
    )

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    impact: Mapped[str] = mapped_column(String(32), nullable=False)
    queue_id: Mapped[str] = mapped_column(String(32), nullable=False)
    assignee_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
