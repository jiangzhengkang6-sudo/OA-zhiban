"""Formal handoff queue and editable ticket drafts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _stamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table("human_queue_item",
        sa.Column("id", pg.UUID(), primary_key=True), sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("thread_id", pg.UUID(), nullable=False), sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("scene", sa.String(16), nullable=False), sa.Column("reason_code", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("assignee_id", sa.String(64)),
        sa.Column("context_summary", sa.Text()), *_stamps())
    op.create_index("ix_human_queue_status_created", "human_queue_item", ["status", "created_at"])
    op.create_index("uq_human_queue_open_reason", "human_queue_item", ["thread_id", "reason_code"], unique=True,
                    postgresql_where=sa.text("status = 'OPEN'"))
    op.create_table("handoff_snapshot",
        sa.Column("id", pg.UUID(), primary_key=True), sa.Column("queue_item_id", pg.UUID(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False), sa.Column("thread_id", pg.UUID(), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False), sa.Column("payload_hash", sa.String(64), nullable=False), *_stamps())
    op.create_index("ix_handoff_snapshot_thread", "handoff_snapshot", ["thread_id"])
    op.create_table("ticket_draft",
        sa.Column("id", pg.UUID(), primary_key=True), sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("thread_id", pg.UUID(), nullable=False, unique=True), sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("fields", pg.JSONB(), nullable=False), sa.Column("extracted_fields", pg.JSONB()),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("confirmation_key", sa.String(128)), *_stamps())
    op.create_index("ix_ticket_draft_thread_status", "ticket_draft", ["thread_id", "status"])


def downgrade():
    connection = op.get_bind()
    for table in ("handoff_snapshot", "human_queue_item", "ticket_draft"):
        if connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError("人工交接或工单草稿含业务数据，禁止直接删除")
    op.drop_table("handoff_snapshot")
    op.drop_table("human_queue_item")
    op.drop_table("ticket_draft")

