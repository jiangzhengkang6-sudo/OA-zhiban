"""用户确认前的可编辑工单草稿。"""

from typing import Optional

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class TicketDraft(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "ticket_draft"
    __table_args__ = (Index("ix_ticket_draft_thread_status", "thread_id", "status"),)

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[object] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False)
    extracted_fields: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    confirmation_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

