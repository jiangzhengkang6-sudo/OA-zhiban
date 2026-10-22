"""Link built-in leave applications to their task threads."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("leave_application", sa.Column("thread_id", pg.UUID(), nullable=True))
    op.create_foreign_key("fk_leave_application_thread_id_agent_thread", "leave_application", "agent_thread", ["thread_id"], ["id"])
    op.create_index("uq_leave_application_thread_id", "leave_application", ["thread_id"], unique=True, postgresql_where=sa.text("thread_id IS NOT NULL"))


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM leave_application WHERE thread_id IS NOT NULL")).scalar_one():
        raise RuntimeError("内置请假申请已关联任务线程，禁止直接删除 thread_id")
    op.drop_index("uq_leave_application_thread_id", table_name="leave_application")
    op.drop_constraint("fk_leave_application_thread_id_agent_thread", "leave_application", type_="foreignkey")
    op.drop_column("leave_application", "thread_id")
