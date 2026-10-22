"""Tenant-owned AI source, policy and audit records for the formal OA path."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .identity import IdentityRow


class OAKnowledgeBinding(Base, IdentityRow):
    __tablename__ = "oa_knowledge_binding"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_id", name="uq_oa_knowledge_binding_source"),
        Index("ix_oa_knowledge_binding_scope", "tenant_id", "department_id", "status"),
    )

    source_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_source.id"), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    department_id: Mapped[str | None] = mapped_column(String(64))
    access_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="owner")
    version_rule: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class OAAgentPolicy(Base, IdentityRow):
    __tablename__ = "oa_agent_policy"
    __table_args__ = (
        UniqueConstraint("tenant_id", "scene", "scope_type", "scope_value", name="uq_oa_agent_policy_scope"),
        Index("ix_oa_agent_policy_lookup", "tenant_id", "scene", "status"),
    )

    scene: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="tenant")
    scope_value: Mapped[str | None] = mapped_column(String(64))
    department_id: Mapped[str | None] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class OAAgentPolicyVersion(Base, IdentityRow):
    __tablename__ = "oa_agent_policy_version"
    __table_args__ = (
        UniqueConstraint("tenant_id", "policy_id", "version", name="uq_oa_agent_policy_version"),
        Index("ix_oa_agent_policy_version_status", "tenant_id", "policy_id", "status"),
    )

    policy_id: Mapped[str] = mapped_column(ForeignKey("oa_agent_policy.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    thresholds: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OABusinessAudit(Base, IdentityRow):
    __tablename__ = "oa_business_audit"
    __table_args__ = (
        Index("ix_oa_business_audit_scope", "tenant_id", "resource", "department_id", "created_at"),
        Index("ix_oa_business_audit_object", "tenant_id", "object_type", "object_id"),
    )

    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    department_id: Mapped[str | None] = mapped_column(String(64))
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(64))
    object_id: Mapped[str | None] = mapped_column(String(128))
    source_type: Mapped[str | None] = mapped_column(String(64))
    source_id: Mapped[str | None] = mapped_column(String(128))
    trace_id: Mapped[str | None] = mapped_column(String(128))
    policy_version: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
