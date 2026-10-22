"""持久化人工服务队列项。"""

from typing import Optional

from sqlalchemy import Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class HumanQueueItem(Base, UUIDMixin, TimestampMixin):
    """脱离图 checkpoint 仍可恢复的人工服务任务。"""

    __tablename__ = "human_queue_item"
    __table_args__ = (
        Index("ix_human_queue_status_created", "status", "created_at"),
        Index("uq_human_queue_open_reason", "thread_id", "reason_code", unique=True,
              postgresql_where=text("status = 'OPEN'")),
    )

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[object] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scene: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    assignee_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    context_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

