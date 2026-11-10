"""统一 OA 智能助手可复核草稿表。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def identity():
    return [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def upgrade():
    op.create_table(
        "assistant_draft",
        *identity(),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("draft_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "missing_required",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("tenant_id", "id", name="uq_assistant_draft_tenant_identity"),
        sa.CheckConstraint(
            "draft_type IN ('task', 'meeting') AND status IN ('DRAFT', 'CONFIRMED', 'CANCELLED')",
            name="assistant_draft_type_status",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["oa_user.tenant_id", "oa_user.id"],
        ),
    )
    op.create_index(
        "ix_assistant_draft_owner",
        "assistant_draft",
        ["tenant_id", "owner_id", "updated_at"],
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM assistant_draft WHERE status = 'CONFIRMED'")
    ):
        raise RuntimeError("已确认草稿关联业务审计记录，请使用前向修复，不支持降级删除")
    op.drop_index("ix_assistant_draft_owner", table_name="assistant_draft")
    op.drop_table("assistant_draft")
