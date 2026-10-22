"""Add built-in leave application, immutable versions and attachment metadata."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _stamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table("leave_application",
        sa.Column("id", pg.UUID(), primary_key=True), sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False), sa.Column("business_id", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("rule_version", sa.String(32)), sa.Column("latest_fields", pg.JSONB(), nullable=False), *_stamps())
    op.create_index("ix_leave_application_owner_status", "leave_application", ["tenant_id", "user_id", "status"])
    op.create_table("leave_application_version",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("application_id", pg.UUID(), sa.ForeignKey("leave_application.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("fields", pg.JSONB(), nullable=False),
        sa.Column("precheck_result", pg.JSONB()), sa.Column("status", sa.String(24), nullable=False), *_stamps(),
        sa.UniqueConstraint("application_id", "version", name="uq_leave_application_version"))
    op.create_index("ix_leave_application_version_application", "leave_application_version", ["application_id", "version"])
    op.create_table("leave_attachment",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("version_id", pg.UUID(), sa.ForeignKey("leave_application_version.id"), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False), sa.Column("storage_ref", sa.String(512), nullable=False),
        sa.Column("scan_status", sa.String(24), nullable=False), *_stamps())
    op.create_index("ix_leave_attachment_version", "leave_attachment", ["version_id"])


def downgrade():
    connection = op.get_bind()
    for table in ("leave_attachment", "leave_application_version", "leave_application"):
        if connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError("内置请假表含业务数据，禁止直接删除")
    op.drop_table("leave_attachment")
    op.drop_table("leave_application_version")
    op.drop_table("leave_application")
