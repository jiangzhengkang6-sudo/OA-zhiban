"""Model token usage and missing-usage markers."""

from typing import Optional
from uuid import UUID

from sqlalchemy import Boolean, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class ModelUsage(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "model_usage"
    __table_args__ = (Index("ix_model_usage_tenant_trace", "tenant_id", "trace_id"),)

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    usage_missing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
