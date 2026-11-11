"""周期规则暂停原因留痕，支持恢复与编辑闭环。"""

from alembic import op
import sqlalchemy as sa

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "assistant_schedule",
        sa.Column("pause_reason", sa.String(length=500), nullable=True),
    )


def downgrade():
    op.drop_column("assistant_schedule", "pause_reason")

