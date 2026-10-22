from uuid import UUID
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, UUIDMixin, TimestampMixin


class ContractSource(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'contract_source'
    __table_args__ = (UniqueConstraint('contract_id', name='uq_contract_source'),)
    contract_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey('contract_record.id'))
    text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    paragraphs: Mapped[list] = mapped_column(JSONB)
    scan_status: Mapped[str] = mapped_column(String(24), default='CLEAN')
    storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

