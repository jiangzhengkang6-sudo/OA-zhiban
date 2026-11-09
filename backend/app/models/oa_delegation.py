"""Time-bounded authority; original workflow seats remain unchanged."""
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base
from .identity import IdentityRow
from .oa_workflow import tenant_key, tenant_fk


class OAApprovalDelegation(Base, IdentityRow):
    __tablename__ = 'oa_approval_delegation'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('delegator_id', 'oa_user'),
        tenant_fk('delegate_id', 'oa_user'), tenant_fk('department_id', 'oa_department'),
        CheckConstraint('delegator_id <> delegate_id', name='delegation_not_self'),
        CheckConstraint('ends_at > starts_at', name='delegation_window'),
        CheckConstraint("scene IN ('leave','reimbursement')", name='delegation_scene'),
        CheckConstraint('revision >= 1', name='delegation_revision'))
    delegator_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    delegate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    department_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scene: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
