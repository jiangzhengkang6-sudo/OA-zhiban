"""统一 OA 智能助手可复核草稿模型。"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .identity import IdentityRow
from .oa_workflow import tenant_fk, tenant_key


class AssistantDraft(Base, IdentityRow):
    """需要人工确认后才允许写入业务库的助手草稿。"""

    __tablename__ = "assistant_draft"
    __table_args__ = (
        tenant_key(__tablename__),
        tenant_fk("owner_id", "oa_user"),
        UniqueConstraint("tenant_id", "id", name="uq_assistant_draft_tenant_identity"),
        Index("ix_assistant_draft_owner", "tenant_id", "owner_id", "updated_at"),
        CheckConstraint(
            "draft_type IN ('task', 'meeting') AND status IN ('DRAFT', 'CONFIRMED', 'CANCELLED')",
            name="assistant_draft_type_status",
        ),
    )

    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    draft_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    missing_required: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
