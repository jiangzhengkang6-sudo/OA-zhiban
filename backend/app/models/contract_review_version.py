from uuid import UUID
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, UUIDMixin, TimestampMixin


class ContractReviewVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = 'contract_review_version'
    __table_args__ = (UniqueConstraint('contract_id', 'version', name='uq_contract_review_version'),)
    contract_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey('contract_record.id'))
    version: Mapped[int] = mapped_column(Integer)
    draft: Mapped[dict] = mapped_column(JSONB)
    edited_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

