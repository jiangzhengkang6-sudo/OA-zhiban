"""Durable notification intent and channel attempt ledger; no legacy resend."""
from alembic import op
import sqlalchemy as sa

revision='0027'
down_revision='0026'
branch_labels=None
depends_on=None


def table(name,*columns,foreign=(),unique=(),checks=()):
    op.create_table(name,sa.Column('id',sa.String(64),primary_key=True),sa.Column('tenant_id',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),*columns,
        sa.UniqueConstraint('tenant_id','id',name='uq_'+name+'_tenant_identity'),
        *(sa.ForeignKeyConstraint(['tenant_id',column],[target+'.tenant_id',target+'.id'],name='fk_'+name+'_'+column) for column,target in foreign),
        *(sa.UniqueConstraint(*keys,name='uq_'+name+'_key_'+str(index)) for index,keys in enumerate(unique)),
        *(sa.CheckConstraint(expression,name=label) for label,expression in checks))


def string(name,size=64,nullable=False): return sa.Column(name,sa.String(size),nullable=nullable)
def moment(name): return sa.Column(name,sa.DateTime(timezone=True))


def upgrade():
    table('oa_user_contact',string('user_id'),string('email',254),sa.Column('enabled',sa.Boolean,nullable=False),
        foreign=(('user_id','oa_user'),),unique=(('tenant_id','user_id'),))
    table('oa_notification',string('source_outbox_id'),string('recipient_id'),string('department_id',nullable=True),
        sa.Column('source',sa.JSON,nullable=False),moment('read_at'),
        foreign=(('source_outbox_id','oa_workflow_outbox'),('recipient_id','oa_user'),('department_id','oa_department')),
        unique=(('tenant_id','source_outbox_id','recipient_id'),))
    table('oa_notification_delivery',string('notification_id'),string('channel',16),string('state',16),string('message_id',128),
        sa.Column('attempt_count',sa.Integer,nullable=False),string('attempt_token',nullable=True),moment('lease_until'),
        moment('next_attempt_at'),string('last_code',nullable=True),foreign=(('notification_id','oa_notification'),),
        unique=(('tenant_id','notification_id','channel'),),checks=(('notification_channel',"channel IN ('inbox','smtp')"),
            ('notification_delivery_state',"state IN ('PENDING','PROCESSING','ACCEPTED','FAILED','UNKNOWN','CANCELLED')"),
            ('notification_attempt_count','attempt_count >= 0')))
    table('oa_notification_attempt',string('delivery_id'),sa.Column('number',sa.Integer,nullable=False),string('token'),
        string('state',16),moment('finished_at'),foreign=(('delivery_id','oa_notification_delivery'),),
        unique=(('tenant_id','delivery_id','number'),('tenant_id','token')),checks=(('notification_attempt_number','number >= 1'),
            ('notification_attempt_state',"state IN ('PROCESSING','ACCEPTED','TEMPORARY','PERMANENT','UNKNOWN')")))
    op.create_index('ix_oa_notification_delivery_notification_id','oa_notification_delivery',['notification_id'])
    op.create_index('ix_oa_notification_delivery_claim','oa_notification_delivery',['channel','state','next_attempt_at'])


def downgrade(): raise RuntimeError('M3 数据应向前修复；禁止直接删除通知和渠道记录')
