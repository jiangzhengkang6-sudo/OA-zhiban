"""Immutable task lifecycle audit events; no source body."""
from uuid import UUID
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, UUIDMixin, TimestampMixin


class WorkTaskEvent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "work_task_event"
    __table_args__ = (UniqueConstraint("task_id", "version", name="uq_work_task_event_version"),)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("work_task.id"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

