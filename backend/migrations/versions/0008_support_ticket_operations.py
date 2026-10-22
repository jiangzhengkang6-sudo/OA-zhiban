"""Add authoritative built-in tickets and assignment rules."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _stamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table("ticket_record",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("ticket_id", sa.String(64), nullable=False, unique=True),
        sa.Column("thread_id", pg.UUID(), nullable=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("impact", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("queue_id", sa.String(32), nullable=True),
        sa.Column("assignee_id", sa.String(64), nullable=True),
        sa.Column("assignment_rule_version", sa.String(64), nullable=True),
        sa.Column("assignment_error", pg.JSONB(), nullable=True),
        sa.Column("merged_from", pg.JSONB(), nullable=True),
        sa.Column("context", pg.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False), *_stamps(),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_ticket_record_idempotency"))
    op.create_index("ix_ticket_record_owner_status", "ticket_record", ["tenant_id", "user_id", "status"])
    op.create_index("ix_ticket_record_queue_status", "ticket_record", ["tenant_id", "queue_id", "status"])
    op.create_table("ticket_assignment_rule",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("impact", sa.String(32), nullable=False),
        sa.Column("queue_id", sa.String(32), nullable=False),
        sa.Column("assignee_id", sa.String(64), nullable=True),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False), *_stamps(),
        sa.UniqueConstraint("tenant_id", "rule_version", "category", "impact", name="uq_ticket_assignment_rule_version"))
    op.create_index("ix_ticket_assignment_rule_lookup", "ticket_assignment_rule",
                    ["tenant_id", "enabled", "category", "impact", "priority"])


def downgrade():
    connection = op.get_bind()
    for table in ("ticket_record", "ticket_assignment_rule"):
        if connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError("工单运营表含业务数据，禁止直接删除")
    op.drop_table("ticket_assignment_rule")
    op.drop_table("ticket_record")
