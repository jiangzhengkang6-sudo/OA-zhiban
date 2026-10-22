"""Expand attachment metadata for private draft uploads without deleting old rows."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('leave_attachment', 'version_id', nullable=True)
    op.add_column('leave_attachment', sa.Column('application_id', pg.UUID(), nullable=True))
    op.add_column('leave_attachment', sa.Column('sha256', sa.String(64), nullable=True))
    op.add_column('leave_attachment', sa.Column('size_bytes', sa.BigInteger(), nullable=True))
    op.add_column('leave_attachment', sa.Column('content_type', sa.String(128), nullable=True))
    op.create_foreign_key('fk_leave_attachment_application', 'leave_attachment', 'leave_application', ['application_id'], ['id'])
    op.create_index('ix_leave_attachment_application', 'leave_attachment', ['application_id'])
    op.execute('UPDATE leave_attachment a SET application_id = v.application_id FROM leave_application_version v WHERE a.version_id = v.id')
    # Legacy metadata has no trustworthy file/hash/scan evidence.
    op.execute("UPDATE leave_attachment SET scan_status = 'PENDING'")


def downgrade():
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM leave_attachment')).scalar_one():
        raise RuntimeError('存在附件，禁止直接移除存储及扫描元数据')
    op.drop_index('ix_leave_attachment_application', table_name='leave_attachment')
    op.drop_constraint('fk_leave_attachment_application', 'leave_attachment', type_='foreignkey')
    for name in ['content_type', 'size_bytes', 'sha256', 'application_id']:
        op.drop_column('leave_attachment', name)
    op.alter_column('leave_attachment', 'version_id', nullable=False)
