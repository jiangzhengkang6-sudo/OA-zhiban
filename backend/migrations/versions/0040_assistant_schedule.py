"""统一助手周期任务规则。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0040"
down_revision = "0039"
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
    op.drop_constraint(
        "assistant_draft_type_status",
        "assistant_draft",
        type_="check",
    )
    op.create_check_constraint(
        "assistant_draft_type_status",
        "assistant_draft",
        "draft_type IN ('task', 'meeting', 'schedule') "
        "AND status IN ('DRAFT', 'CONFIRMED', 'CANCELLED')",
    )

    op.create_table(
        "assistant_schedule",
        *identity(),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("day_of_week", sa.Integer),
        sa.Column("day_of_month", sa.Integer),
        sa.Column("run_time", sa.Time(timezone=True), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("max_occurrences", sa.Integer),
        sa.Column("occurrence_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "template",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_assistant_schedule_tenant_identity"),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'PAUSED', 'CANCELLED', 'COMPLETED')",
            name="assistant_schedule_status",
        ),
        sa.CheckConstraint(
            "frequency IN ('daily', 'weekly', 'monthly')",
            name="assistant_schedule_frequency",
        ),
        sa.CheckConstraint(
            "(day_of_week IS NULL OR (day_of_week BETWEEN 0 AND 6)) "
            "AND (day_of_month IS NULL OR (day_of_month BETWEEN 1 AND 28))",
            name="assistant_schedule_days",
        ),
        sa.CheckConstraint(
            "occurrence_count >= 0 AND (max_occurrences IS NULL OR max_occurrences >= 1)",
            name="assistant_schedule_limits",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_id"],
            ["oa_user.tenant_id", "oa_user.id"],
            name="fk_assistant_schedule_owner",
        ),
    )
    op.create_index(
        "ix_assistant_schedule_owner",
        "assistant_schedule",
        ["tenant_id", "owner_id", "updated_at"],
    )
    op.create_index(
        "ix_assistant_schedule_due",
        "assistant_schedule",
        ["next_run_at"],
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade():
    bind = op.get_bind()
    if bind.scalar(
        sa.text(
            "SELECT count(*) FROM assistant_schedule "
            "WHERE status IN ('ACTIVE', 'PAUSED', 'COMPLETED')"
        )
    ):
        raise RuntimeError("已启用周期规则关联业务任务，请使用前向修复，不支持降级删除")
    op.drop_index("ix_assistant_schedule_due", table_name="assistant_schedule")
    op.drop_index("ix_assistant_schedule_owner", table_name="assistant_schedule")
    op.drop_table("assistant_schedule")
    op.drop_constraint(
        "assistant_draft_type_status",
        "assistant_draft",
        type_="check",
    )
    op.create_check_constraint(
        "assistant_draft_type_status",
        "assistant_draft",
        "draft_type IN ('task', 'meeting') "
        "AND status IN ('DRAFT', 'CONFIRMED', 'CANCELLED')",
    )

