"""Owner-only task extraction batch; source snapshots remain private."""
from uuid import UUID
from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, UUIDMixin, TimestampMixin


class WorkTaskBatch(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "work_task_batch"
    __table_args__ = (UniqueConstraint("batch_id", name="uq_work_task_batch_public"),
        UniqueConstraint("tenant_id", "owner_id", "idempotency_key", name="uq_work_task_batch_create"),
        Index("ix_work_task_batch_owner", "tenant_id", "owner_id"))
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("agent_thread.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CREATED")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    error: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

