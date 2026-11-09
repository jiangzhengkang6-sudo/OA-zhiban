"""Add opt-in Tencent video rooms, preserving existing meeting arrangements."""
from alembic import op
import sqlalchemy as sa

revision = '0035'
down_revision = '0034'
branch_labels = None
depends_on = None


def upgrade():
    # 0034 uses ORM metadata; a fresh install can already have these columns.
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('oa_meeting')}
    for name in ('video_enabled', 'video_room_created'):
        if name not in columns:
            op.add_column('oa_meeting', sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM oa_meeting WHERE video_enabled OR video_room_created')):
        raise RuntimeError('已有视频会议，禁止破坏性降级，请向前修复')
    op.drop_column('oa_meeting', 'video_room_created')
    op.drop_column('oa_meeting', 'video_enabled')
