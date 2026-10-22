"""Stable knowledge source identity shared by all historical versions."""

from typing import Optional

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class KnowledgeSource(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "knowledge_source"
    __table_args__ = (Index("ix_knowledge_source_tenant_name", "tenant_id", "name"),)

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="document")
    owner_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
