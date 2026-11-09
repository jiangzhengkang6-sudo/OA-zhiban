"""Tenant-scoped manual workflow records, independent of agent checkpoints."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base
from .identity import IdentityRow


def tenant_key(table):
    return UniqueConstraint('tenant_id', 'id', name='uq_' + table + '_tenant_identity')


def tenant_fk(column, table):
    return ForeignKeyConstraint(['tenant_id', column], [table + '.tenant_id', table + '.id'],
                               name='fk_' + table.removeprefix('oa_') + '_' + column)


class OAWorkflowDefinition(Base, IdentityRow):
    __tablename__ = 'oa_workflow_definition'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('department_id', 'oa_department'),
        UniqueConstraint('tenant_id', 'department_id', 'code'), CheckConstraint('revision >= 1', name='definition_revision'))
    department_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    scene: Mapped[str] = mapped_column(String(32), default='leave', nullable=False)
    draft: Mapped[dict] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    published_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class OAWorkflowVersion(Base, IdentityRow):
    __tablename__ = 'oa_workflow_version'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('definition_id', 'oa_workflow_definition'),
        tenant_fk('published_by', 'oa_user'), UniqueConstraint('tenant_id', 'definition_id', 'version'))
    definition_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    form_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    package: Mapped[dict] = mapped_column(JSON, nullable=False)
    workflow_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    form_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_by: Mapped[str] = mapped_column(String(64), nullable=False)


class OAWorkflowInstance(Base, IdentityRow):
    __tablename__ = 'oa_workflow_instance'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('leave_version_id', 'oa_leave_version'),
        tenant_fk('reimbursement_version_id', 'oa_reimbursement_version'),
        UniqueConstraint('tenant_id', 'leave_version_id'),
        UniqueConstraint('tenant_id', 'reimbursement_version_id', name='uq_oa_workflow_instance_reimbursement_version'),
        CheckConstraint("(scene = 'leave' AND leave_version_id IS NOT NULL AND reimbursement_version_id IS NULL) OR "
            "(scene = 'reimbursement' AND reimbursement_version_id IS NOT NULL AND leave_version_id IS NULL)",name='instance_subject'),
        CheckConstraint('route_revision >= 1 AND revision >= 1', name='instance_revision'),
        CheckConstraint("state IN ('IN_REVIEW','PAUSED','APPROVED','REJECTED','CANCELLED')", name='instance_state'))
    scene: Mapped[str] = mapped_column(String(32), default='leave', server_default='leave', nullable=False)
    leave_version_id: Mapped[str | None] = mapped_column(String(64))
    reimbursement_version_id: Mapped[str | None] = mapped_column(String(64))
    route_snapshot: Mapped[list] = mapped_column(JSON, nullable=False)
    route_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    state: Mapped[str] = mapped_column(String(24), default='IN_REVIEW', nullable=False)
    pause_reason: Mapped[str | None] = mapped_column(String(500))


class OAWorkflowNode(Base, IdentityRow):
    __tablename__ = 'oa_workflow_node'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('instance_id', 'oa_workflow_instance'),
        UniqueConstraint('tenant_id', 'instance_id', 'ordinal'),
        CheckConstraint("state IN ('WAITING','ACTIVE','DONE','CANCELLED')", name='node_state'))
    instance_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    node_key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str | None] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16), default='WAITING', nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAWorkflowSeat(Base, IdentityRow):
    __tablename__ = 'oa_workflow_seat'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('node_id', 'oa_workflow_node'),
        tenant_fk('original_user_id', 'oa_user'), tenant_fk('effective_user_id', 'oa_user'),
        ForeignKeyConstraint(['tenant_id', 'decision_delegation_id'], ['oa_approval_delegation.tenant_id', 'oa_approval_delegation.id'], name='fk_seat_decision_delegation'),
        UniqueConstraint('tenant_id', 'node_id', 'effective_user_id'),
        CheckConstraint("state IN ('PENDING','APPROVED','REJECTED','CANCELLED','CC')", name='seat_state'))
    node_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    original_user_id: Mapped[str | None] = mapped_column(String(64))
    effective_user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    eligibility: Mapped[dict] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default='PENDING', nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    substituted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(64))
    decision_delegation_id: Mapped[str | None] = mapped_column(String(64))
    decision_note: Mapped[str | None] = mapped_column(String(2000))


class OAWorkflowOperation(Base, IdentityRow):
    __tablename__ = 'oa_workflow_operation'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('actor_id', 'oa_user'),
        UniqueConstraint('tenant_id', 'kind', 'target_id', 'target_version', 'operation_id', name='uq_oa_workflow_command_key'))
    actor_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_version: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)


class OAWorkflowEvent(Base, IdentityRow):
    __tablename__ = 'oa_workflow_event'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('operation_id', 'oa_workflow_operation'),
        tenant_fk('actor_id', 'oa_user'), UniqueConstraint('tenant_id', 'event_key'))
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    event_key: Mapped[str] = mapped_column(String(256), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(128))
    target_version: Mapped[str | None] = mapped_column(String(64))
    changes: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}', nullable=False)


class OAWorkflowOutbox(Base, IdentityRow):
    __tablename__ = 'oa_workflow_outbox'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('event_id', 'oa_workflow_event'),
        tenant_fk('recipient_id', 'oa_user'), UniqueConstraint('tenant_id', 'event_id', 'recipient_id'),
        CheckConstraint("status IN ('PENDING','SENT','FAILED')", name='outbox_status'))
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    recipient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default='PENDING', nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
