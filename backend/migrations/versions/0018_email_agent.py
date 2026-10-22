"""Add local mail analysis and reply revision tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("email_record",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("email_id", sa.String(64), nullable=False),
        sa.Column("thread_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_thread.id"), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("input_snapshot", pg.JSONB(), nullable=False),
        sa.Column("source_snapshot", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("confirmation", pg.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("error_trace_id", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("email_id", name="uq_email_record_email_id"),
        sa.UniqueConstraint("tenant_id", "owner_id", "idempotency_key", name="uq_email_record_create_idempotency"))
    op.create_index("ix_email_record_owner_status", "email_record", ["tenant_id", "owner_id", "status"])
    op.create_table("email_draft_version",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("email_id", pg.UUID(as_uuid=True), sa.ForeignKey("email_record.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("draft", pg.JSONB(), nullable=False),
        sa.Column("checks", pg.JSONB(), nullable=False),
        sa.Column("edited_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("email_id", "version", name="uq_email_draft_version_number"))
    op.create_index("ix_email_draft_version_email_created", "email_draft_version", ["email_id", "created_at"])


def downgrade():
    for table in ("email_draft_version", "email_record"):
        if op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError(f"{table} contains business data; downgrade refused")
    op.drop_index("ix_email_draft_version_email_created", table_name="email_draft_version")
    op.drop_table("email_draft_version")
    op.drop_index("ix_email_record_owner_status", table_name="email_record")
    op.drop_table("email_record")
