"""Formal reimbursement snapshots; money is stored as integer CNY cents."""
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base
from .identity import IdentityRow
from .oa_workflow import tenant_key, tenant_fk


class OAReimbursement(Base, IdentityRow):
    __tablename__ = 'oa_reimbursement'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('applicant_id','oa_user'),
        tenant_fk('department_id','oa_department'),tenant_fk('workflow_definition_id','oa_workflow_definition'),
        UniqueConstraint('tenant_id','business_no'),
        CheckConstraint("state IN ('DRAFT','IN_REVIEW','PAUSED','APPROVED','REJECTED','CANCELLED')",name='reimbursement_state'),
        CheckConstraint('revision >= 1 AND submission_version >= 0',name='reimbursement_revision'))
    business_no: Mapped[str] = mapped_column(String(64),nullable=False)
    applicant_id: Mapped[str] = mapped_column(String(64),nullable=False,index=True)
    department_id: Mapped[str] = mapped_column(String(64),nullable=False)
    workflow_definition_id: Mapped[str] = mapped_column(String(64),nullable=False)
    fields: Mapped[dict] = mapped_column(JSON,nullable=False)
    revision: Mapped[int] = mapped_column(Integer,default=1,nullable=False)
    submission_version: Mapped[int] = mapped_column(Integer,default=0,nullable=False)
    state: Mapped[str] = mapped_column(String(24),default='DRAFT',nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAReimbursementVersion(Base, IdentityRow):
    __tablename__ = 'oa_reimbursement_version'
    __table_args__ = (tenant_key(__tablename__),tenant_fk('reimbursement_id','oa_reimbursement'),
        tenant_fk('workflow_version_id','oa_workflow_version'),UniqueConstraint('tenant_id','reimbursement_id','version'),
        CheckConstraint('version >= 1',name='reimbursement_version_positive'),
        CheckConstraint('amount_cents BETWEEN 1 AND 99999999999',name='reimbursement_amount'),
        CheckConstraint("currency = 'CNY'",name='reimbursement_currency'))
    reimbursement_id: Mapped[str] = mapped_column(String(64),nullable=False,index=True)
    version: Mapped[int] = mapped_column(Integer,nullable=False)
    workflow_version_id: Mapped[str] = mapped_column(String(64),nullable=False)
    fields: Mapped[dict] = mapped_column(JSON,nullable=False)
    attachments: Mapped[list] = mapped_column(JSON,nullable=False)
    precheck: Mapped[dict] = mapped_column(JSON,nullable=False)
    differences: Mapped[dict] = mapped_column(JSON,nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger,nullable=False)
    currency: Mapped[str] = mapped_column(String(3),nullable=False,default='CNY')


class OAReimbursementAttachment(Base, IdentityRow):
    __tablename__ = 'oa_reimbursement_attachment'
    __table_args__ = (tenant_key(__tablename__),tenant_fk('reimbursement_id','oa_reimbursement'),
        tenant_fk('uploaded_by','oa_user'),CheckConstraint('size > 0',name='reimbursement_attachment_size'),
        CheckConstraint("scan_status IN ('CLEAN','PENDING','REJECTED','FAILED')",name='reimbursement_attachment_scan'))
    reimbursement_id: Mapped[str] = mapped_column(String(64),nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(64),nullable=False)
    filename: Mapped[str] = mapped_column(String(255),nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128),nullable=False)
    size: Mapped[int] = mapped_column(Integer,nullable=False)
    sha256: Mapped[str] = mapped_column(String(64),nullable=False)
    storage_key: Mapped[str] = mapped_column(String(128),nullable=False)
    scan_status: Mapped[str] = mapped_column(String(16),default='PENDING',nullable=False)
