"""Expand with ordered approval instances; preserve legacy human decisions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def stamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table("approval_instance",
        sa.Column("id", pg.UUID(), primary_key=True), sa.Column("thread_id", pg.UUID(), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False), sa.Column("business_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("route_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("external_request_id", sa.String(128)), *stamps(),
        sa.UniqueConstraint("thread_id", "version", name="uq_approval_thread_version"))
    op.create_index("ix_approval_instance_tenant_status", "approval_instance", ["tenant_id", "status"])
    op.create_table("approval_node",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("instance_id", pg.UUID(), sa.ForeignKey("approval_instance.id"), nullable=False),
        sa.Column("node_order", sa.Integer(), nullable=False), sa.Column("approver_id", sa.String(64), nullable=False),
        sa.Column("approver_name", sa.String(128), nullable=False), sa.Column("is_proxy", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("waiting_since", sa.DateTime(timezone=True)), sa.Column("last_nudge_at", sa.DateTime(timezone=True)),
        sa.Column("escalated_at", sa.DateTime(timezone=True)), *stamps(),
        sa.UniqueConstraint("instance_id", "node_order", name="uq_approval_node_order"))
    op.create_index("uq_approval_node_one_active", "approval_node", ["instance_id"], unique=True,
                    postgresql_where=sa.text("status = 'ACTIVE'"))
    op.create_index("ix_approval_node_actor_status", "approval_node", ["approver_id", "status"])
    op.create_table("approval_decision",
        sa.Column("id", pg.UUID(), primary_key=True),
        sa.Column("instance_id", pg.UUID(), sa.ForeignKey("approval_instance.id"), nullable=False),
        sa.Column("node_id", pg.UUID(), sa.ForeignKey("approval_node.id"), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False), sa.Column("action", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False), sa.Column("edited_data", pg.JSONB()),
        sa.Column("payload_hash", sa.String(64), nullable=False), sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("result_status", sa.String(32), nullable=False), *stamps(),
        sa.UniqueConstraint("instance_id", "idempotency_key", name="uq_approval_decision_command"))


def downgrade():
    connection = op.get_bind()
    if any(connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
           for table in ("approval_decision", "approval_node", "approval_instance")):
        raise RuntimeError("审批实例含业务数据，禁止删除；请从备份恢复")
    for table in ("approval_decision", "approval_node", "approval_instance"):
        op.drop_table(table)
