"""Department announcement publication and explicit reading receipts."""
from alembic import op
import sqlalchemy as sa

revision = '0031'
down_revision = '0030'
branch_labels = None
depends_on = None


def identity_columns():
    return [sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def fk(column, table):
    return sa.ForeignKeyConstraint(['tenant_id', column], [table + '.tenant_id', table + '.id'])


def upgrade():
    op.create_table('oa_announcement', *identity_columns(),
        sa.Column('department_id', sa.String(64), nullable=False),
        sa.Column('author_id', sa.String(64), nullable=False),
        sa.Column('title', sa.String(200), nullable=False), sa.Column('body', sa.Text(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True)), sa.Column('withdrawn_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_oa_announcement_tenant_identity'),
        sa.CheckConstraint('revision >= 1', name='announcement_revision'),
        sa.CheckConstraint("state IN ('DRAFT','PUBLISHED','WITHDRAWN')", name='announcement_state'),
        fk('department_id', 'oa_department'), fk('author_id', 'oa_user'))
    op.create_index('ix_oa_announcement_department_id', 'oa_announcement', ['department_id'])
    op.create_table('oa_announcement_read', *identity_columns(),
        sa.Column('announcement_id', sa.String(64), nullable=False),
        sa.Column('reader_id', sa.String(64), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_oa_announcement_read_tenant_identity'),
        sa.UniqueConstraint('tenant_id', 'announcement_id', 'reader_id'),
        fk('announcement_id', 'oa_announcement'), fk('reader_id', 'oa_user'))


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text('SELECT EXISTS (SELECT 1 FROM oa_announcement)')).scalar():
        raise RuntimeError('已有公告和阅读历史，禁止破坏性降级，请使用向前修复')
    op.drop_table('oa_announcement_read')
    op.drop_table('oa_announcement')
