"""Opt-in, department-scoped WeCom webhook delivery ledger."""
from alembic import op
import sqlalchemy as sa

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('oa_user_contact', sa.Column('wecom_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('oa_notification_delivery', sa.Column('destination_hash', sa.String(64), nullable=True))
    op.create_index('ix_oa_notification_delivery_destination_hash', 'oa_notification_delivery', ['destination_hash'])
    op.drop_constraint(op.f('ck_oa_notification_delivery_notification_channel'), 'oa_notification_delivery', type_='check')
    op.create_check_constraint('notification_channel', 'oa_notification_delivery', "channel IN ('inbox','smtp','wecom')")


def downgrade():
    raise RuntimeError('企微授权和投递历史必须保留，请使用向前修复迁移')
