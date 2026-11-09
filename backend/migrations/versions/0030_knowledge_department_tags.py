"""Preserve full formal department IDs in version permission tags."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('knowledge_version', 'permission_tags',
        existing_type=pg.ARRAY(sa.String(32)), type_=pg.ARRAY(sa.String(64)),
        existing_nullable=False)


def downgrade():
    raise RuntimeError('正式部门权限编号必须完整保留，请使用向前修复迁移')
