"""Formal tenant-scoped knowledge, policy and business audit authority."""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def _table(name, *columns, unique=(), indexes=()):
    op.create_table(
        name,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *columns,
        sa.UniqueConstraint("tenant_id", "id", name=f"uq_{name}_tenant_identity"),
        *(sa.UniqueConstraint(*fields, name=f"uq_{name}_{i}") for i, fields in enumerate(unique)),
    )
    for name_, columns_ in indexes:
        op.create_index(name_, name, columns_)


def upgrade():
    _table("oa_knowledge_binding",
        sa.Column("source_id", sa.UUID(as_uuid=True), sa.ForeignKey("knowledge_source.id"), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False), sa.Column("department_id", sa.String(64)),
        sa.Column("access_scope", sa.String(16), nullable=False, server_default="owner"),
        sa.Column("version_rule", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        unique=(("tenant_id", "source_id"),),
        indexes=(("ix_oa_knowledge_binding_scope", ("tenant_id", "department_id", "status")),))
    _table("oa_agent_policy",
        sa.Column("scene", sa.String(64), nullable=False), sa.Column("scope_type", sa.String(16), nullable=False, server_default="tenant"),
        sa.Column("scope_value", sa.String(64)), sa.Column("department_id", sa.String(64)),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        unique=(("tenant_id", "scene", "scope_type", "scope_value"),),
        indexes=(("ix_oa_agent_policy_lookup", ("tenant_id", "scene", "status")),))
    _table("oa_agent_policy_version",
        sa.Column("policy_id", sa.String(64), sa.ForeignKey("oa_agent_policy.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False), sa.Column("thresholds", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("rule_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.String(64), nullable=False), sa.Column("published_at", sa.DateTime(timezone=True)),
        unique=(("tenant_id", "policy_id", "version"),),
        indexes=(("ix_oa_agent_policy_version_status", ("tenant_id", "policy_id", "status")),))
    _table("oa_business_audit",
        sa.Column("actor_id", sa.String(64), nullable=False), sa.Column("department_id", sa.String(64)),
        sa.Column("resource", sa.String(64), nullable=False), sa.Column("action", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(64)), sa.Column("object_id", sa.String(128)),
        sa.Column("source_type", sa.String(64)), sa.Column("source_id", sa.String(128)),
        sa.Column("trace_id", sa.String(128)), sa.Column("policy_version", sa.String(64)),
        sa.Column("result", sa.String(16), nullable=False, server_default="success"),
        sa.Column("detail", sa.JSON, nullable=False, server_default="{}"),
        indexes=(("ix_oa_business_audit_scope", ("tenant_id", "resource", "department_id", "created_at")),
                 ("ix_oa_business_audit_object", ("tenant_id", "object_type", "object_id"))))


def downgrade():
    raise RuntimeError("M3 正式范围数据向前修复；禁止直接删除")
