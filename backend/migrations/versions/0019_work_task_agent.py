"""Independent business tasks, immutable candidates, events and private reminders."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def base_columns():
    return [sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def string(name, size=64, nullable=False):
    return sa.Column(name, sa.String(size), nullable=nullable)


def upgrade():
    op.create_table("work_task_batch", *base_columns(), string("batch_id"),
        sa.Column("thread_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_thread.id"), nullable=False),
        string("tenant_id"), string("owner_id"), string("source_type", 16), string("source_id"), string("source_version"),
        sa.Column("source_snapshot", pg.JSONB(), nullable=False), string("status", 24),
        sa.Column("current_version", sa.Integer(), nullable=False), string("idempotency_key", 128),
        sa.Column("error", pg.JSONB(), nullable=True),
        sa.UniqueConstraint("batch_id", name="uq_work_task_batch_public"),
        sa.UniqueConstraint("tenant_id", "owner_id", "idempotency_key", name="uq_work_task_batch_create"))
    op.create_index("ix_work_task_batch_owner", "work_task_batch", ["tenant_id", "owner_id"])
    op.create_table("work_task_draft_version", *base_columns(),
        sa.Column("batch_id", pg.UUID(as_uuid=True), sa.ForeignKey("work_task_batch.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("candidates", pg.JSONB(), nullable=False),
        string("edited_by", nullable=True),
        sa.UniqueConstraint("batch_id", "version", name="uq_work_task_draft_version"))
    op.create_table("work_task", *base_columns(), string("task_id"),
        sa.Column("batch_id", pg.UUID(as_uuid=True), sa.ForeignKey("work_task_batch.id"), nullable=False),
        string("tenant_id"), string("creator_id"), string("assignee_id"), string("source_type", 16),
        string("source_id"), string("source_version"), string("candidate_id"),
        sa.Column("source_refs", pg.JSONB(), nullable=False), string("title", 255), string("priority", 16),
        sa.Column("sensitive", sa.Boolean(), nullable=False), sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        string("status", 24), sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("deadline_version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_work_task_public"),
        sa.UniqueConstraint("tenant_id", "source_type", "source_id", "source_version", "candidate_id", name="uq_work_task_candidate"))
    op.create_index("ix_work_task_actor", "work_task", ["tenant_id", "creator_id", "assignee_id"])
    op.create_index("ix_work_task_due", "work_task", ["status", "due_at"])
    op.create_table("work_task_event", *base_columns(),
        sa.Column("task_id", pg.UUID(as_uuid=True), sa.ForeignKey("work_task.id"), nullable=False),
        string("actor_id"), string("action", 24), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("details", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("task_id", "version", name="uq_work_task_event_version"))
    op.create_table("work_task_notification", *base_columns(),
        sa.Column("task_id", pg.UUID(as_uuid=True), sa.ForeignKey("work_task.id"), nullable=False),
        string("tenant_id"), sa.Column("deadline_version", sa.Integer(), nullable=False),
        string("stage", 24), string("recipient_id"), sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("task_id", "deadline_version", "stage", "recipient_id", name="uq_work_task_notification_stage"))


def downgrade():
    tables = ("work_task_notification", "work_task_event", "work_task", "work_task_draft_version", "work_task_batch")
    for table in tables:
        if op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError(f"{table} contains business data; downgrade refused")
    for table in tables:
        op.drop_table(table)
