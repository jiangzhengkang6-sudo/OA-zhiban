"""Add command and runtime infrastructure; no changes to MVP business rows."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def upgrade():
    op.create_table("idempotency_record",
        sa.Column("id", pg.UUID(), primary_key=True), sa.Column("command_id", pg.UUID(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False), sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False), sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False), sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("result", pg.JSONB()), sa.Column("external_request_id", sa.String(128)),
        sa.Column("trace_id", sa.String(64), nullable=False), *timestamps(),
        sa.UniqueConstraint("tenant_id", "actor_id", "resource_type", "resource_id", "idempotency_key", name="uq_idempotency_scope"),
        sa.CheckConstraint("status IN ('PENDING','SUCCEEDED','FAILED','UNKNOWN')", name="ck_idempotency_record_valid_status"))
    op.create_index("ix_idempotency_record_status_created", "idempotency_record", ["status", "created_at"])
    op.create_table("runtime_span",
        sa.Column("id", pg.UUID(), primary_key=True), sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False), sa.Column("run_id", pg.UUID(), nullable=False),
        sa.Column("thread_id", pg.UUID()), sa.Column("node_name", sa.String(64), nullable=False), sa.Column("tool_name", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(32)), *timestamps())
    op.create_index("ix_runtime_span_tenant_trace", "runtime_span", ["tenant_id", "trace_id"])


def downgrade():
    connection = op.get_bind()
    for name in ("runtime_span", "idempotency_record"):
        if connection.execute(sa.text(f"SELECT COUNT(*) FROM {name}")).scalar_one():
            raise RuntimeError("基础表已有记录，禁止直接回退删除；请先备份并制定恢复方案")
    op.drop_table("runtime_span")
    op.drop_table("idempotency_record")
