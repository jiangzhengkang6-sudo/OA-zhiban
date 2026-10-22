"""Formal tickets and trusted confirmations; preserve legacy ticket tables."""
from alembic import op
import sqlalchemy as sa

revision='0026'
down_revision='0025'
branch_labels=None
depends_on=None


def table(name,*columns,foreign=(),unique=(),checks=()):
    op.create_table(name,sa.Column('id',sa.String(64),primary_key=True),sa.Column('tenant_id',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),*columns,
        sa.UniqueConstraint('tenant_id','id',name='uq_'+name+'_tenant_identity'),
        *(sa.ForeignKeyConstraint(['tenant_id',column],[target+'.tenant_id',target+'.id'],name='fk_'+name+'_'+column) for column,target in foreign),
        *(sa.UniqueConstraint(*keys) for keys in unique),*(sa.CheckConstraint(expression,name=label) for label,expression in checks))


def string(name,size=64,nullable=False):
    return sa.Column(name,sa.String(size),nullable=nullable)


def upgrade():
    table('oa_ticket_assignment_rule',string('department_id'),string('code'),sa.Column('version',sa.Integer,nullable=False),
        string('category'),string('impact'),string('queue',128),string('assignee_id',nullable=True),
        sa.Column('priority',sa.Integer,nullable=False),sa.Column('enabled',sa.Boolean,nullable=False),
        foreign=(('department_id','oa_department'),('assignee_id','oa_user')),
        unique=(('tenant_id','department_id','code','version'),),checks=(('ticket_rule_version','version >= 1'),))
    table('oa_ticket',string('business_no'),string('owner_id'),string('department_id'),sa.Column('revision',sa.Integer,nullable=False),
        string('state',24),string('category'),string('priority',16),string('impact'),string('summary',2000),string('queue',128,True),
        string('assignee_id',nullable=True),string('assignment_rule_id',nullable=True),sa.Column('assignment_rule_version',sa.Integer),
        string('assignment_error',500,True),sa.Column('merged_requests',sa.JSON,nullable=False),string('resolution_note',2000,True),
        foreign=(('owner_id','oa_user'),('department_id','oa_department'),('assignee_id','oa_user'),('assignment_rule_id','oa_ticket_assignment_rule')),
        unique=(('tenant_id','business_no'),),checks=(('ticket_revision','revision >= 1'),('formal_ticket_state',"state IN ('OPEN','IN_PROGRESS','RESOLVED','CLOSED')")))
    table('oa_ticket_feedback',string('ticket_id'),string('actor_id'),string('operation_id'),sa.Column('resolved',sa.Boolean,nullable=False),string('comment',2000),
        foreign=(('ticket_id','oa_ticket'),('actor_id','oa_user'),('operation_id','oa_workflow_operation')),unique=(('tenant_id','operation_id'),))
    table('oa_bridge_confirmation',string('actor_id'),string('thread_id',nullable=True),string('action'),string('object_id'),string('object_version'),
        string('payload_hash'),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),string('consumed_operation_id',nullable=True),
        foreign=(('actor_id','oa_user'),('consumed_operation_id','oa_workflow_operation')))
    table('oa_bridge_result',string('actor_id'),string('method'),string('original_key'),string('target_id'),string('target_version'),string('operation_id'),
        sa.Column('result',sa.JSON,nullable=False),foreign=(('actor_id','oa_user'),('operation_id','oa_workflow_operation')),
        unique=(('tenant_id','actor_id','method','original_key'),))
    op.create_index('ix_oa_ticket_owner_id','oa_ticket',['owner_id'])
    op.create_index('ix_oa_ticket_assignee_id','oa_ticket',['assignee_id'])
    op.create_index('ix_oa_ticket_feedback_ticket_id','oa_ticket_feedback',['ticket_id'])


def downgrade():
    raise RuntimeError('M3 数据应向前修复；禁止直接删除正式工单和确认记录')
