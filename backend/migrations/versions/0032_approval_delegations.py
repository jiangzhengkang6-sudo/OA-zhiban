"""Self-service approval delegation and immutable decision attribution."""
from alembic import op
import sqlalchemy as sa

revision = '0032'
down_revision = '0031'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('oa_approval_delegation',
        sa.Column('id', sa.String(64), primary_key=True), sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('delegator_id', sa.String(64), nullable=False), sa.Column('delegate_id', sa.String(64), nullable=False),
        sa.Column('department_id', sa.String(64), nullable=False), sa.Column('scene', sa.String(32), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False), sa.Column('revoked_at', sa.DateTime(timezone=True)),
        sa.Column('reason', sa.String(500), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_oa_approval_delegation_tenant_identity'),
        sa.ForeignKeyConstraint(['tenant_id', 'delegator_id'], ['oa_user.tenant_id', 'oa_user.id'], name='fk_user_delegator_id'),
        sa.ForeignKeyConstraint(['tenant_id', 'delegate_id'], ['oa_user.tenant_id', 'oa_user.id'], name='fk_user_delegate_id'),
        sa.ForeignKeyConstraint(['tenant_id', 'department_id'], ['oa_department.tenant_id', 'oa_department.id'], name='fk_department_department_id'),
        sa.CheckConstraint('delegator_id <> delegate_id', name='delegation_not_self'),
        sa.CheckConstraint('ends_at > starts_at', name='delegation_window'),
        sa.CheckConstraint("scene IN ('leave','reimbursement')", name='delegation_scene'),
        sa.CheckConstraint('revision >= 1', name='delegation_revision'))
    op.create_index('ix_oa_approval_delegation_delegator_id', 'oa_approval_delegation', ['delegator_id'])
    op.create_index('ix_oa_approval_delegation_delegate_id', 'oa_approval_delegation', ['delegate_id'])
    op.add_column('oa_workflow_seat', sa.Column('decision_delegation_id', sa.String(64)))
    op.create_foreign_key('fk_seat_decision_delegation', 'oa_workflow_seat', 'oa_approval_delegation',
        ['tenant_id', 'decision_delegation_id'], ['tenant_id', 'id'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM oa_approval_delegation')):
        raise RuntimeError('已有委托记录，禁止破坏性降级，请向前修复')
    op.drop_constraint('fk_seat_decision_delegation', 'oa_workflow_seat', type_='foreignkey')
    op.drop_column('oa_workflow_seat', 'decision_delegation_id')
    op.drop_table('oa_approval_delegation')
