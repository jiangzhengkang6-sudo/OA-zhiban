"""Owner-private report plans, snapshots and immutable review versions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("report_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", sa.String(64), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_thread.id"), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False), sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False), sa.Column("plan", postgresql.JSONB(), nullable=False),
        sa.Column("scope_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("plan_confirmation", postgresql.JSONB()), sa.Column("cached_snapshot", postgresql.JSONB()),
        sa.Column("publication", postgresql.JSONB()), sa.Column("error_code", sa.String(32)),
        sa.Column("error_trace_id", sa.String(64)), sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("report_id", name="uq_report_record_report_id"),
        sa.UniqueConstraint("tenant_id", "owner_id", "idempotency_key", name="uq_report_record_create_idempotency"))
    op.create_index("ix_report_record_owner_status", "report_record", ["tenant_id", "owner_id", "status"])
    op.create_table("report_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("report_record.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("draft", postgresql.JSONB(), nullable=False), sa.Column("edited_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("report_id", "version", name="uq_report_version_number"))


def downgrade():
    for table in ("report_version", "report_record"):
        if op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError(f"{table} contains business data; downgrade refused")
    op.drop_table("report_version")
    op.drop_index("ix_report_record_owner_status", table_name="report_record")
    op.drop_table("report_record")
