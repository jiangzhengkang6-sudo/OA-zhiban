"""Add administrator-controlled degradation state."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "degradation_state",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("scene", sa.String(16), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="global"),
        sa.Column("scope_value", sa.String(64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("new_task_action", sa.String(16), nullable=False, server_default="fallback"),
        sa.Column("inflight_action", sa.String(16), nullable=False, server_default="continue"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("restored_by", sa.String(64), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_degradation_state_lookup",
        "degradation_state",
        ["scene", "scope_type", "scope_value", "enabled"],
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM degradation_state")).scalar_one():
        raise RuntimeError("降级状态含业务数据，禁止直接删除")
    op.drop_index("ix_degradation_state_lookup", table_name="degradation_state")
    op.drop_table("degradation_state")
