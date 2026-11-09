"""Restricted group notification receipts; old rows remain non-replayable."""
from alembic import op
import sqlalchemy as sa

revision = '0037'
down_revision = '0036'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('oa_wecom_batch',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('destination_hash', sa.String(64), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('tenant_id','id',name='uq_oa_wecom_batch_tenant_identity'),
        sa.CheckConstraint("state IN ('PROCESSING','ACCEPTED','TEMPORARY','PERMANENT','UNKNOWN','CANCELLED')",name='wecom_batch_state'))
    op.create_index('ix_oa_wecom_batch_destination_hash','oa_wecom_batch',['destination_hash'])
    for name, size in [('wecom_batch_id',64),('wecom_event_key',64),('wecom_business_key',128),('wecom_category',32)]:
        op.add_column('oa_notification_delivery',sa.Column(name,sa.String(size)))
        if name!='wecom_category': op.create_index('ix_oa_notification_delivery_'+name,'oa_notification_delivery',[name])
    op.create_foreign_key('fk_wecom_batch_wecom_batch_id','oa_notification_delivery','oa_wecom_batch',
        ['tenant_id','wecom_batch_id'],['tenant_id','id'])
    op.add_column('oa_notification_attempt',sa.Column('wecom_batch_id',sa.String(64)))
    op.create_index('ix_oa_notification_attempt_wecom_batch_id','oa_notification_attempt',['wecom_batch_id'])
    op.create_foreign_key('fk_wecom_batch_wecom_batch_id','oa_notification_attempt','oa_wecom_batch',
        ['tenant_id','wecom_batch_id'],['tenant_id','id'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM oa_wecom_batch')):
        raise RuntimeError('群通知投递历史必须保留，请采用前向修复或完整备份恢复')
    op.drop_constraint('fk_wecom_batch_wecom_batch_id','oa_notification_attempt',type_='foreignkey')
    op.drop_index('ix_oa_notification_attempt_wecom_batch_id',table_name='oa_notification_attempt')
    op.drop_column('oa_notification_attempt','wecom_batch_id')
    op.drop_constraint('fk_wecom_batch_wecom_batch_id','oa_notification_delivery',type_='foreignkey')
    for name in ['wecom_batch_id','wecom_event_key','wecom_business_key','wecom_category']:
        if name!='wecom_category': op.drop_index('ix_oa_notification_delivery_'+name,table_name='oa_notification_delivery')
        op.drop_column('oa_notification_delivery',name)
    op.drop_index('ix_oa_wecom_batch_destination_hash',table_name='oa_wecom_batch')
    op.drop_table('oa_wecom_batch')
