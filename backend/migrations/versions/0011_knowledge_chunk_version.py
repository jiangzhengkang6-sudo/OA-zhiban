"""Allow chunks to cite an immutable knowledge version."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy import inspect

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("knowledge_chunk")}
    if "version_id" not in columns:
        op.add_column("knowledge_chunk", sa.Column("version_id", pg.UUID(as_uuid=True), nullable=True))
    foreign_keys = inspector.get_foreign_keys("knowledge_chunk")
    has_version_fk = any(
        fk.get("referred_table") == "knowledge_version"
        and fk.get("constrained_columns") == ["version_id"]
        for fk in foreign_keys
    )
    if not has_version_fk:
        op.create_foreign_key(
            "fk_knowledge_chunk_version_id",
            "knowledge_chunk",
            "knowledge_version",
            ["version_id"],
            ["id"],
        )
    indexes = {index["name"] for index in inspector.get_indexes("knowledge_chunk")}
    if "ix_knowledge_chunk_version" not in indexes:
        op.create_index("ix_knowledge_chunk_version", "knowledge_chunk", ["version_id", "chunk_index"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM knowledge_chunk WHERE version_id IS NOT NULL")).scalar_one():
        raise RuntimeError("知识切片已绑定版本，禁止删除版本引用")
    op.drop_index("ix_knowledge_chunk_version", table_name="knowledge_chunk")
    op.drop_constraint("fk_knowledge_chunk_version_id", "knowledge_chunk", type_="foreignkey")
    op.drop_column("knowledge_chunk", "version_id")
