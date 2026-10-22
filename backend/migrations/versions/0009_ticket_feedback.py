"""Add idempotent ticket feedback and review loop storage."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ticket_feedback",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("ticket_id", sa.String(64), nullable=False),
        sa.Column("thread_id", pg.UUID(), nullable=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_ticket_feedback_idempotency"),
    )
    op.create_index("ix_ticket_feedback_ticket", "ticket_feedback", ["tenant_id", "ticket_id"])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM ticket_feedback")).scalar_one():
        raise RuntimeError("反馈表含业务数据，禁止直接删除")
    op.drop_table("ticket_feedback")
