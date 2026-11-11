"""统一 OA 智能助手周期任务规则模型。"""

from datetime import datetime, time

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .identity import IdentityRow


class AssistantSchedule(Base, IdentityRow):
    """用户确认后启用的低风险周期任务规则。"""

    __tablename__ = "assistant_schedule"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_assistant_schedule_tenant_identity"),
        ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["oa_user.tenant_id", "oa_user.id"],
            name="fk_assistant_schedule_owner",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'PAUSED', 'CANCELLED', 'COMPLETED')",
            name="assistant_schedule_status",
        ),
        CheckConstraint(
            "frequency IN ('daily', 'weekly', 'monthly')",
            name="assistant_schedule_frequency",
        ),
        CheckConstraint(
            "(day_of_week IS NULL OR (day_of_week BETWEEN 0 AND 6)) "
            "AND (day_of_month IS NULL OR (day_of_month BETWEEN 1 AND 28))",
            name="assistant_schedule_days",
        ),
        CheckConstraint(
            "occurrence_count >= 0 AND (max_occurrences IS NULL OR max_occurrences >= 1)",
            name="assistant_schedule_limits",
        ),
        Index("ix_assistant_schedule_owner", "tenant_id", "owner_id", "updated_at"),
        Index(
            "ix_assistant_schedule_due",
            "next_run_at",
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    frequency: Mapped[str] = mapped_column(String(16), nullable=False)
    day_of_week: Mapped[int | None] = mapped_column(Integer)
    day_of_month: Mapped[int | None] = mapped_column(Integer)
    run_time: Mapped[time] = mapped_column(Time(timezone=True), nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_occurrences: Mapped[int | None] = mapped_column(Integer)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    template: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pause_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

