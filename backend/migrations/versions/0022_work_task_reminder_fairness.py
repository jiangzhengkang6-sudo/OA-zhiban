"""Persist reminder scan order so unavailable sources cannot starve later tasks."""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("work_task", sa.Column("notification_scan_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_work_task_reminder_scan", "work_task", ["status", "notification_scan_at", "due_at"])


def downgrade():
    op.drop_index("ix_work_task_reminder_scan", table_name="work_task")
    op.drop_column("work_task", "notification_scan_at")
