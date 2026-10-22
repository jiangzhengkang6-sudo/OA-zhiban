"""Manual leave snapshots and integer-day accounting."""
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base
from .identity import IdentityRow
from .oa_workflow import tenant_key, tenant_fk


class OALeave(Base, IdentityRow):
    __tablename__ = 'oa_leave'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('applicant_id', 'oa_user'),
        tenant_fk('department_id', 'oa_department'), tenant_fk('workflow_definition_id', 'oa_workflow_definition'),
        UniqueConstraint('tenant_id', 'business_no'),
        CheckConstraint("state IN ('DRAFT','IN_REVIEW','PAUSED','APPROVED','REJECTED','CANCELLED')", name='leave_state'),
        CheckConstraint('revision >= 1 AND submission_version >= 0', name='leave_revision'))
    business_no: Mapped[str] = mapped_column(String(64), nullable=False)
    applicant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    department_id: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_definition_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fields: Mapped[dict] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    submission_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    state: Mapped[str] = mapped_column(String(24), default='DRAFT', nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OALeaveVersion(Base, IdentityRow):
    __tablename__ = 'oa_leave_version'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('leave_id', 'oa_leave'),
        tenant_fk('workflow_version_id', 'oa_workflow_version'), UniqueConstraint('tenant_id', 'leave_id', 'version'),
        CheckConstraint('end_date >= start_date AND days >= 1', name='version_dates'))
    leave_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fields: Mapped[dict] = mapped_column(JSON, nullable=False)
    attachments: Mapped[list] = mapped_column(JSON, nullable=False)
    precheck: Mapped[dict] = mapped_column(JSON, nullable=False)
    differences: Mapped[dict] = mapped_column(JSON, nullable=False)
    leave_type: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)


class OALeaveBalance(Base, IdentityRow):
    __tablename__ = 'oa_leave_balance'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('user_id', 'oa_user'),
        UniqueConstraint('tenant_id', 'user_id', 'leave_type', 'year'),
        CheckConstraint('total >= used + reserved AND used >= 0 AND reserved >= 0', name='balance_nonnegative'))
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    leave_type: Mapped[str] = mapped_column(String(64), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class OALeaveLedger(Base, IdentityRow):
    __tablename__ = 'oa_leave_ledger'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('balance_id', 'oa_leave_balance'),
        tenant_fk('leave_version_id', 'oa_leave_version'), tenant_fk('operation_id', 'oa_workflow_operation'),
        UniqueConstraint('tenant_id', 'balance_id', 'leave_version_id', 'kind'),
        CheckConstraint("kind IN ('ADJUST','RESERVE','CONSUME','RELEASE')", name='ledger_kind'))
    balance_id: Mapped[str] = mapped_column(String(64), nullable=False)
    leave_version_id: Mapped[str | None] = mapped_column(String(64))
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    total_delta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    used_delta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_delta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    before: Mapped[dict] = mapped_column(JSON, nullable=False)
    after: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)


class OALeaveAttachment(Base, IdentityRow):
    __tablename__ = 'oa_leave_attachment'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('leave_id', 'oa_leave'),
        tenant_fk('uploaded_by', 'oa_user'), CheckConstraint('size > 0', name='attachment_size'),
        CheckConstraint("scan_status IN ('CLEAN','PENDING','REJECTED','FAILED')", name='attachment_scan'))
    leave_id: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(16), default='PENDING', nullable=False)
