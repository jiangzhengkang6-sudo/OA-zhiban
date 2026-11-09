"""Public office mailbox. No credentials or automatic mailbox access in migrations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table('public_mailbox', sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), unique=True, nullable=False),
        sa.Column('name', sa.String(128), nullable=False), sa.Column('address', sa.String(320), nullable=False),
        sa.Column('config_digest', sa.String(64), nullable=False),
        sa.Column('uid_validity', sa.String(64), nullable=False, server_default=''),
        sa.Column('last_uid', sa.Integer, nullable=False, server_default='0'),
        sa.Column('synced_at', sa.DateTime(timezone=True)),
        sa.Column('revision', sa.Integer, nullable=False, server_default='1'), *timestamps())
    op.create_table('public_mailbox_member',
        sa.Column('mailbox_id', sa.String(64), sa.ForeignKey('public_mailbox.id'), primary_key=True),
        sa.Column('user_id', sa.String(64), primary_key=True),
        sa.Column('can_process', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('can_send', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('can_manage', sa.Boolean, nullable=False, server_default=sa.false()))
    op.create_table('public_mail_message', sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('mailbox_id', sa.String(64), sa.ForeignKey('public_mailbox.id'), nullable=False, index=True),
        sa.Column('direction', sa.String(16), nullable=False), sa.Column('remote_key', sa.String(128)),
        sa.Column('message_id', sa.String(998), nullable=False), sa.Column('sender', sa.String(320), nullable=False),
        sa.Column('recipients', JSONB, nullable=False), sa.Column('subject', sa.String(255), nullable=False),
        sa.Column('body', sa.Text, nullable=False), sa.Column('attachments', JSONB, nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True)), sa.Column('status', sa.String(24), nullable=False),
        sa.Column('claimed_by', sa.String(64)), sa.Column('created_by', sa.String(64)),
        sa.Column('sent_by', sa.String(64)),
        sa.Column('reply_to_id', sa.String(64), sa.ForeignKey('public_mail_message.id')),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('create_key', sa.String(128)), sa.Column('create_digest', sa.String(64)), *timestamps(),
        sa.UniqueConstraint('mailbox_id', 'remote_key', name='uq_public_mail_remote'),
        sa.UniqueConstraint('mailbox_id', 'created_by', 'create_key', name='uq_public_mail_create'))
    op.create_table('public_mail_import',
        sa.Column('message_id', sa.String(64), sa.ForeignKey('public_mail_message.id'), primary_key=True),
        sa.Column('user_id', sa.String(64), primary_key=True), sa.Column('email_id', sa.String(64), nullable=False))


def downgrade():
    op.drop_table('public_mail_import')
    op.drop_table('public_mail_message')
    op.drop_table('public_mailbox_member')
    op.drop_table('public_mailbox')
