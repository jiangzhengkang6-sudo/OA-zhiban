"""Add text-only meeting agent domain tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "meeting_record",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("thread_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_thread.id"), nullable=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("error_trace_id", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("meeting_id", name="uq_meeting_record_meeting_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_meeting_record_tenant_idempotency"),
    )
    op.create_index("ix_meeting_record_tenant_status", "meeting_record", ["tenant_id", "status"])
    op.create_index("ix_meeting_record_owner_created", "meeting_record", ["owner_id", "created_at"])

    op.create_table(
        "meeting_source",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_id", pg.UUID(as_uuid=True), sa.ForeignKey("meeting_record.id"), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_ref", sa.String(255), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_meeting_source_meeting_created", "meeting_source", ["meeting_id", "created_at"])

    op.create_table(
        "meeting_segment",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_id", pg.UUID(as_uuid=True), sa.ForeignKey("meeting_record.id"), nullable=False),
        sa.Column("source_id", pg.UUID(as_uuid=True), sa.ForeignKey("meeting_source.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("locator", pg.JSONB(), nullable=False),
        sa.Column("summary", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("meeting_id", "ordinal", name="uq_meeting_segment_ordinal"),
    )
    op.create_index("ix_meeting_segment_source_order", "meeting_segment", ["source_id", "ordinal"])

    op.create_table(
        "meeting_draft_version",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_id", pg.UUID(as_uuid=True), sa.ForeignKey("meeting_record.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("topics", pg.JSONB(), nullable=False),
        sa.Column("decisions", pg.JSONB(), nullable=False),
        sa.Column("action_items", pg.JSONB(), nullable=False),
        sa.Column("source_refs", pg.JSONB(), nullable=False),
        sa.Column("edited_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("meeting_id", "version", name="uq_meeting_draft_version_number"),
    )
    op.create_index("ix_meeting_draft_version_meeting_status", "meeting_draft_version", ["meeting_id", "status"])

    op.create_table(
        "meeting_decision",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("meeting_id", pg.UUID(as_uuid=True), sa.ForeignKey("meeting_record.id"), nullable=False),
        sa.Column("draft_version_id", pg.UUID(as_uuid=True), sa.ForeignKey("meeting_draft_version.id"), nullable=True),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", pg.JSONB(), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("meeting_id", "idempotency_key", name="uq_meeting_decision_idempotency"),
    )
    op.create_index("ix_meeting_decision_meeting_created", "meeting_decision", ["meeting_id", "created_at"])


def downgrade():
    bind = op.get_bind()
    for table in ("meeting_decision", "meeting_draft_version", "meeting_segment", "meeting_source", "meeting_record"):
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError(f"{table} 含业务数据，禁止直接删除")
    op.drop_index("ix_meeting_decision_meeting_created", table_name="meeting_decision")
    op.drop_table("meeting_decision")
    op.drop_index("ix_meeting_draft_version_meeting_status", table_name="meeting_draft_version")
    op.drop_table("meeting_draft_version")
    op.drop_index("ix_meeting_segment_source_order", table_name="meeting_segment")
    op.drop_table("meeting_segment")
    op.drop_index("ix_meeting_source_meeting_created", table_name="meeting_source")
    op.drop_table("meeting_source")
    op.drop_index("ix_meeting_record_owner_created", table_name="meeting_record")
    op.drop_index("ix_meeting_record_tenant_status", table_name="meeting_record")
    op.drop_table("meeting_record")

