"""Add non-destructive knowledge source/version/file metadata tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "knowledge_source",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="document"),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_knowledge_source_tenant_name", "knowledge_source", ["tenant_id", "name"])
    op.create_table(
        "knowledge_version",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", pg.UUID(as_uuid=True), sa.ForeignKey("knowledge_source.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("permission_tags", pg.ARRAY(sa.String(32)), nullable=False, server_default="{}"),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("parse_status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_knowledge_version_source_status", "knowledge_version", ["source_id", "status"])
    op.create_index("ix_knowledge_version_effective", "knowledge_version", ["status", "effective_at", "expire_at"])
    op.create_table(
        "knowledge_file",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("version_id", pg.UUID(as_uuid=True), sa.ForeignKey("knowledge_version.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_ref", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_knowledge_file_version", "knowledge_file", ["version_id"])


def downgrade():
    bind = op.get_bind()
    for table in ("knowledge_file", "knowledge_version", "knowledge_source"):
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError(f"{table} 含业务数据，禁止直接删除")
    op.drop_table("knowledge_file")
    op.drop_index("ix_knowledge_version_effective", table_name="knowledge_version")
    op.drop_index("ix_knowledge_version_source_status", table_name="knowledge_version")
    op.drop_table("knowledge_version")
    op.drop_index("ix_knowledge_source_tenant_name", table_name="knowledge_source")
    op.drop_table("knowledge_source")
