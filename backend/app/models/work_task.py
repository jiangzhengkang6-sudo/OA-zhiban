"""Business task lifecycle independent of AgentThread."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, UUIDMixin, TimestampMixin


class WorkTask(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "work_task"
    __table_args__ = (UniqueConstraint("task_id", name="uq_work_task_public"),
        UniqueConstraint("tenant_id", "source_type", "source_id", "source_version", "candidate_id", name="uq_work_task_candidate"),
        Index("ix_work_task_actor", "tenant_id", "creator_id", "assignee_id"),
        Index("ix_work_task_due", "status", "due_at"),
        Index("ix_work_task_reminder_scan", "status", "notification_scan_at", "due_at"))
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("work_task_batch.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    creator_id: Mapped[str] = mapped_column(String(64), nullable=False)
    assignee_id: Mapped[str] = mapped_column(String(64), nullable=False)
    handoff_department_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_refs: Mapped[list] = mapped_column(JSONB, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    sensitive: Mapped[bool] = mapped_column(nullable=False, default=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deadline_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notification_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

