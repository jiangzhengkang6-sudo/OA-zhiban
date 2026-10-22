"""Add controlled audit export metadata."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_export",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("requested_by", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
        sa.Column("filters", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("storage_ref", sa.String(512), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_export_requested_by_created", "audit_export", ["requested_by", "created_at"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM audit_export")).scalar_one():
        raise RuntimeError("审计导出含业务数据，禁止直接删除")
    op.drop_index("ix_audit_export_requested_by_created", table_name="audit_export")
    op.drop_table("audit_export")
