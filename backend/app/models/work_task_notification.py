"""Private internal reminder records; never external messages."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, UUIDMixin, TimestampMixin


class WorkTaskNotification(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "work_task_notification"
    __table_args__ = (UniqueConstraint("task_id", "deadline_version", "stage", "recipient_id", name="uq_work_task_notification_stage"),)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("work_task.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    deadline_version: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    recipient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
