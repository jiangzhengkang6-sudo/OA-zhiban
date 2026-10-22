"""人工交接时保存的脱敏上下文快照。"""

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class HandoffSnapshot(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "handoff_snapshot"
    __table_args__ = (Index("ix_handoff_snapshot_thread", "thread_id"),)

    queue_item_id: Mapped[object] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[object] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

