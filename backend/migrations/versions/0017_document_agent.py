"""Add platform-local document drafting tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "document_record",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("thread_id", pg.UUID(as_uuid=True), sa.ForeignKey("agent_thread.id"), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("template_id", sa.String(32), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("template_sections", pg.JSONB(), nullable=False),
        sa.Column("input_snapshot", pg.JSONB(), nullable=False),
        sa.Column("source_snapshot", pg.JSONB(), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("recipient", sa.String(500), nullable=False),
        sa.Column("deadline", sa.String(100), nullable=False),
        sa.Column("classification", sa.String(24), nullable=False),
        sa.Column("distribution", sa.String(500), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("error_trace_id", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("confirmation", pg.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("document_id", name="uq_document_record_document_id"),
        sa.UniqueConstraint("tenant_id", "owner_id", "idempotency_key", name="uq_document_record_create_idempotency"),
    )
    op.create_index("ix_document_record_owner_status", "document_record", ["tenant_id", "owner_id", "status"])
    op.create_table(
        "document_draft_version",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", pg.UUID(as_uuid=True), sa.ForeignKey("document_record.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_refs", pg.JSONB(), nullable=False),
        sa.Column("checks", pg.JSONB(), nullable=False),
        sa.Column("edited_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("document_id", "version", name="uq_document_draft_version_number"),
    )
    op.create_index("ix_document_draft_version_document_created", "document_draft_version", ["document_id", "created_at"])


def downgrade():
    bind = op.get_bind()
    for table in ("document_draft_version", "document_record"):
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError(f"{table} 含业务数据，禁止直接删除")
    op.drop_index("ix_document_draft_version_document_created", table_name="document_draft_version")
    op.drop_table("document_draft_version")
    op.drop_index("ix_document_record_owner_status", table_name="document_record")
    op.drop_table("document_record")
