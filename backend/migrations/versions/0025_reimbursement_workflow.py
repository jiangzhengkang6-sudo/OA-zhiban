"""Add typed workflow subjects without rewriting existing leave business data."""
from alembic import op
import sqlalchemy as sa

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def table(name, *columns, foreign=(), unique=(), checks=()):
    op.create_table(name,sa.Column('id',sa.String(64),primary_key=True),
        sa.Column('tenant_id',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        *columns,sa.UniqueConstraint('tenant_id','id',name='uq_'+name+'_tenant_identity'),
        *(sa.ForeignKeyConstraint(['tenant_id',col],[target+'.tenant_id',target+'.id'],
            name='fk_'+target.removeprefix('oa_')+'_'+col) for col,target in foreign),
        *(sa.UniqueConstraint(*keys) for keys in unique),
        *(sa.CheckConstraint(expr,name=label) for label,expr in checks))


def string(name, size=64):
    return sa.Column(name,sa.String(size),nullable=False)


def integer(name, default=None):
    return sa.Column(name,sa.Integer,nullable=False,server_default=str(default) if default is not None else None)


def json(name):
    return sa.Column(name,sa.JSON,nullable=False)


def upgrade():
    table('oa_reimbursement',string('business_no'),string('applicant_id'),string('department_id'),
        string('workflow_definition_id'),json('fields'),integer('revision',1),integer('submission_version',0),
        string('state',24),sa.Column('archived_at',sa.DateTime(timezone=True)),
        foreign=[('applicant_id','oa_user'),('department_id','oa_department'),('workflow_definition_id','oa_workflow_definition')],
        unique=[('tenant_id','business_no')],checks=[('reimbursement_state',"state IN ('DRAFT','IN_REVIEW','PAUSED','APPROVED','REJECTED','CANCELLED')"),
            ('reimbursement_revision','revision >= 1 AND submission_version >= 0')])
    table('oa_reimbursement_version',string('reimbursement_id'),integer('version'),string('workflow_version_id'),
        json('fields'),json('attachments'),json('precheck'),json('differences'),
        sa.Column('amount_cents',sa.BigInteger,nullable=False),string('currency',3),
        foreign=[('reimbursement_id','oa_reimbursement'),('workflow_version_id','oa_workflow_version')],
        unique=[('tenant_id','reimbursement_id','version')],checks=[('reimbursement_version_positive','version >= 1'),
            ('reimbursement_amount','amount_cents BETWEEN 1 AND 99999999999'),('reimbursement_currency',"currency = 'CNY'")])
    table('oa_reimbursement_attachment',string('reimbursement_id'),string('uploaded_by'),string('filename',255),
        string('mime_type',128),integer('size'),string('sha256'),string('storage_key',128),string('scan_status',16),
        foreign=[('reimbursement_id','oa_reimbursement'),('uploaded_by','oa_user')],
        checks=[('reimbursement_attachment_size','size > 0'),('reimbursement_attachment_scan',"scan_status IN ('CLEAN','PENDING','REJECTED','FAILED')")])
    op.add_column('oa_workflow_instance',sa.Column('scene',sa.String(32),nullable=False,server_default='leave'))
    op.add_column('oa_workflow_instance',sa.Column('reimbursement_version_id',sa.String(64)))
    op.alter_column('oa_workflow_instance','leave_version_id',existing_type=sa.String(64),nullable=True)
    op.create_foreign_key('fk_reimbursement_version_reimbursement_version_id','oa_workflow_instance',
        'oa_reimbursement_version',['tenant_id','reimbursement_version_id'],['tenant_id','id'])
    op.create_unique_constraint('uq_oa_workflow_instance_reimbursement_version','oa_workflow_instance',['tenant_id','reimbursement_version_id'])
    op.create_check_constraint('instance_subject','oa_workflow_instance',
        "(scene = 'leave' AND leave_version_id IS NOT NULL AND reimbursement_version_id IS NULL) OR "
        "(scene = 'reimbursement' AND reimbursement_version_id IS NOT NULL AND leave_version_id IS NULL)")
    op.add_column('oa_workflow_event',sa.Column('trace_id',sa.String(128)))
    op.add_column('oa_workflow_event',sa.Column('target_version',sa.String(64)))
    op.add_column('oa_workflow_event',sa.Column('changes',sa.JSON,nullable=False,server_default='{}'))
    for name,column in [('oa_reimbursement','applicant_id'),('oa_reimbursement_version','reimbursement_id')]:
        op.create_index('ix_'+name+'_'+column,name,[column])


def downgrade():
    raise RuntimeError('M3 数据应向前修复；禁止直接删除正式业务表')
