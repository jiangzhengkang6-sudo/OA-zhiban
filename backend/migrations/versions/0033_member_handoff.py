"""Preserve explicit administrative task handoff authority.

Revision ID: 0033
Revises: 0032
"""
from alembic import op
import sqlalchemy as sa

revision = '0033'
down_revision = '0032'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('work_task', sa.Column('handoff_department_id', sa.String(64), nullable=True))


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM work_task WHERE handoff_department_id IS NOT NULL')):
        raise RuntimeError('已有成员交接记录，禁止破坏性降级，请向前修复')
    op.drop_column('work_task', 'handoff_department_id')
