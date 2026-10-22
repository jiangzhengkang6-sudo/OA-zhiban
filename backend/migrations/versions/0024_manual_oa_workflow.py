"""Add tenant-scoped manual leave and workflow authority, without legacy rewrites."""
from alembic import op
import sqlalchemy as sa

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def _table(name, *columns, foreign=(), unique=(), checks=()):
    # All target references include tenant_id; plain IDs never cross a tenant boundary.
    op.create_table(name, sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *columns, sa.UniqueConstraint('tenant_id', 'id', name='uq_' + name + '_tenant_identity'),
        *(sa.ForeignKeyConstraint(['tenant_id', col], [target + '.tenant_id', target + '.id'],
            name='fk_' + target.removeprefix('oa_') + '_' + col) for col, target in foreign),
        *(sa.UniqueConstraint(*keys) for keys in unique),
        *(sa.CheckConstraint(expression, name=label) for label, expression in checks))


def _str(name, size=64, nullable=False):
    return sa.Column(name, sa.String(size), nullable=nullable)


def _int(name, default=None):
    return sa.Column(name, sa.Integer, nullable=False, server_default=str(default) if default is not None else None)


def _json(name):
    return sa.Column(name, sa.JSON, nullable=False)


def upgrade():
    _table('oa_workflow_definition', _str('department_id'), _str('code'), _str('name',128), _str('scene',32),
        _json('draft'), _int('revision',1), _int('published_version',0),
        foreign=[('department_id','oa_department')], unique=[('tenant_id','department_id','code')],
        checks=[('definition_revision','revision >= 1')])
    _table('oa_workflow_version', _str('definition_id'), _int('version'), _int('form_version'), _int('rule_version'),
        _json('package'), _str('workflow_hash'), _str('form_hash'), _str('rule_hash'), _str('published_by'),
        foreign=[('definition_id','oa_workflow_definition'),('published_by','oa_user')], unique=[('tenant_id','definition_id','version')])
    _table('oa_leave', _str('business_no'), _str('applicant_id'), _str('department_id'), _str('workflow_definition_id'),
        _json('fields'), _int('revision',1), _int('submission_version',0), _str('state',24),
        sa.Column('archived_at',sa.DateTime(timezone=True)),
        foreign=[('applicant_id','oa_user'),('department_id','oa_department'),('workflow_definition_id','oa_workflow_definition')],
        unique=[('tenant_id','business_no')], checks=[('leave_state',"state IN ('DRAFT','IN_REVIEW','PAUSED','APPROVED','REJECTED','CANCELLED')"),
            ('leave_revision','revision >= 1 AND submission_version >= 0')])
    _table('oa_leave_version', _str('leave_id'), _int('version'), _str('workflow_version_id'), _json('fields'),
        _json('attachments'), _json('precheck'), _json('differences'), _str('leave_type'),
        sa.Column('start_date',sa.Date,nullable=False), sa.Column('end_date',sa.Date,nullable=False), _int('days'),
        foreign=[('leave_id','oa_leave'),('workflow_version_id','oa_workflow_version')], unique=[('tenant_id','leave_id','version')],
        checks=[('version_dates','end_date >= start_date AND days >= 1')])
    _table('oa_workflow_instance', _str('leave_version_id'), _json('route_snapshot'), _int('route_revision',1), _int('revision',1),
        _str('state',24), _str('pause_reason',500,True), foreign=[('leave_version_id','oa_leave_version')],
        unique=[('tenant_id','leave_version_id')], checks=[('instance_revision','route_revision >= 1 AND revision >= 1'),
            ('instance_state',"state IN ('IN_REVIEW','PAUSED','APPROVED','REJECTED','CANCELLED')")])
    _table('oa_workflow_node', _str('instance_id'), _int('ordinal'), _str('node_key'), _str('kind',16), _str('mode',16,True),
        _str('state',16), _int('revision',1), sa.Column('due_at',sa.DateTime(timezone=True)),
        foreign=[('instance_id','oa_workflow_instance')], unique=[('tenant_id','instance_id','ordinal')],
        checks=[('node_state',"state IN ('WAITING','ACTIVE','DONE','CANCELLED')")])
    _table('oa_workflow_seat', _str('node_id'), _str('original_user_id',nullable=True), _str('effective_user_id',nullable=True),
        _json('eligibility'), _str('state',16), _int('revision',1),
        sa.Column('substituted',sa.Boolean,nullable=False,server_default=sa.false()),
        sa.Column('escalated',sa.Boolean,nullable=False,server_default=sa.false()), _str('decided_by',nullable=True),
        _str('decision_note',2000,True), foreign=[('node_id','oa_workflow_node'),('original_user_id','oa_user'),('effective_user_id','oa_user')],
        unique=[('tenant_id','node_id','effective_user_id')], checks=[('seat_state',"state IN ('PENDING','APPROVED','REJECTED','CANCELLED','CC')")])
    _table('oa_workflow_operation', _str('actor_id',nullable=True), _str('kind',40), _str('target_id'),
        _str('target_version'), _str('operation_id'), _str('payload_hash'), _json('result'), foreign=[('actor_id','oa_user')])
    op.create_unique_constraint('uq_oa_workflow_command_key','oa_workflow_operation',
        ['tenant_id','kind','target_id','target_version','operation_id'])
    _table('oa_workflow_event', _str('operation_id'), _str('actor_id',nullable=True), _str('event_key',256),
        _str('action'), _str('target_id'), _json('detail'), foreign=[('operation_id','oa_workflow_operation'),('actor_id','oa_user')],
        unique=[('tenant_id','event_key')])
    _table('oa_workflow_outbox', _str('event_id'), _str('recipient_id'), _str('status',16), _json('payload'),
        foreign=[('event_id','oa_workflow_event'),('recipient_id','oa_user')], unique=[('tenant_id','event_id','recipient_id')],
        checks=[('outbox_status',"status IN ('PENDING','SENT','FAILED')")])
    _table('oa_leave_balance', _str('user_id'), _str('leave_type'), _int('year'), _int('total'), _int('used',0),
        _int('reserved',0), _int('revision',1), foreign=[('user_id','oa_user')], unique=[('tenant_id','user_id','leave_type','year')],
        checks=[('balance_nonnegative','total >= used + reserved AND used >= 0 AND reserved >= 0')])
    _table('oa_leave_ledger', _str('balance_id'), _str('leave_version_id',nullable=True), _str('operation_id'), _str('kind',16),
        _int('total_delta',0), _int('used_delta',0), _int('reserved_delta',0), _json('before'), _json('after'), _str('reason',500),
        foreign=[('balance_id','oa_leave_balance'),('leave_version_id','oa_leave_version'),('operation_id','oa_workflow_operation')],
        unique=[('tenant_id','balance_id','leave_version_id','kind')], checks=[('ledger_kind',"kind IN ('ADJUST','RESERVE','CONSUME','RELEASE')")])
    _table('oa_leave_attachment', _str('leave_id'), _str('uploaded_by'), _str('filename',255), _str('mime_type',128),
        _int('size'), _str('sha256'), _str('storage_key',128), _str('scan_status',16),
        foreign=[('leave_id','oa_leave'),('uploaded_by','oa_user')], checks=[('attachment_size','size > 0'),
            ('attachment_scan',"scan_status IN ('CLEAN','PENDING','REJECTED','FAILED')")])
    for table, column in [('oa_leave','applicant_id'),('oa_leave_version','leave_id'),('oa_workflow_node','instance_id'),
            ('oa_workflow_seat','node_id'),('oa_workflow_seat','effective_user_id'),('oa_workflow_event','target_id')]:
        op.create_index('ix_' + table + '_' + column, table, [column])


def downgrade():
    raise RuntimeError('M2 数据应向前修复；禁止直接删除正式业务表')
