"""Add immutable policy version snapshots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "policy_version",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("scene", sa.String(16), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="global"),
        sa.Column("scope_value", sa.String(64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("thresholds", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rule_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_policy_version_scope_status", "policy_version", ["scene", "scope_type", "scope_value", "status"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM policy_version")).scalar_one():
        raise RuntimeError("策略版本含业务数据，禁止直接删除")
    op.drop_index("ix_policy_version_scope_status", table_name="policy_version")
    op.drop_table("policy_version")
