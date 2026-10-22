"""Append-only candidate versions."""
from uuid import UUID
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, UUIDMixin, TimestampMixin


class WorkTaskDraftVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "work_task_draft_version"
    __table_args__ = (UniqueConstraint("batch_id", "version", name="uq_work_task_draft_version"),)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("work_task_batch.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    candidates: Mapped[list] = mapped_column(JSONB, nullable=False)
    edited_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

