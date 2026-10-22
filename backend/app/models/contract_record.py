from uuid import UUID
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, UUIDMixin, TimestampMixin


class ContractRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'contract_record'
    __table_args__ = (UniqueConstraint('contract_id', name='uq_contract_public'),
        UniqueConstraint('tenant_id', 'owner_id', 'idempotency_key', name='uq_contract_create'),
        Index('ix_contract_participants', 'tenant_id', 'owner_id', 'reviewer_id'))
    contract_id: Mapped[str] = mapped_column(String(64))
    thread_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey('agent_thread.id'))
    tenant_id: Mapped[str] = mapped_column(String(64))
    owner_id: Mapped[str] = mapped_column(String(64))
    reviewer_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default='CREATED')
    current_version: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    node_state: Mapped[dict] = mapped_column(JSONB, default=dict)
    confirmation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

