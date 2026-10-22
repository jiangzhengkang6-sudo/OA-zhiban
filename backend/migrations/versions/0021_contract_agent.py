"""Private contract inputs, review history and decisions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0021'
down_revision = '0020'
branch_labels = depends_on = None


def base_columns():
    return [sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table('contract_record', *base_columns(),
        sa.Column('contract_id', sa.String(64), nullable=False),
        sa.Column('thread_id', pg.UUID(as_uuid=True), sa.ForeignKey('agent_thread.id'), nullable=False),
        sa.Column('tenant_id', sa.String(64), nullable=False), sa.Column('owner_id', sa.String(64), nullable=False),
        sa.Column('reviewer_id', sa.String(64), nullable=False), sa.Column('title', sa.String(255), nullable=False),
        sa.Column('status', sa.String(24), nullable=False), sa.Column('current_version', sa.Integer(), nullable=True),
        sa.Column('idempotency_key', sa.String(128), nullable=False), sa.Column('node_state', pg.JSONB(), nullable=False),
        sa.Column('confirmation', pg.JSONB(), nullable=True), sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_trace_id', sa.String(64), nullable=True),
        sa.UniqueConstraint('contract_id', name='uq_contract_public'),
        sa.UniqueConstraint('tenant_id', 'owner_id', 'idempotency_key', name='uq_contract_create'))
    op.create_index('ix_contract_participants', 'contract_record', ['tenant_id','owner_id','reviewer_id'])
    op.create_table('contract_source', *base_columns(),
        sa.Column('contract_id', pg.UUID(as_uuid=True), sa.ForeignKey('contract_record.id'), nullable=False),
        sa.Column('text', sa.Text(), nullable=False), sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('paragraphs', pg.JSONB(), nullable=False), sa.Column('scan_status', sa.String(24), nullable=False),
        sa.Column('storage_key', sa.String(255), nullable=True), sa.Column('filename', sa.String(255), nullable=True),
        sa.UniqueConstraint('contract_id', name='uq_contract_source'))
    op.create_table('contract_review_version', *base_columns(),
        sa.Column('contract_id', pg.UUID(as_uuid=True), sa.ForeignKey('contract_record.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('draft', pg.JSONB(), nullable=False),
        sa.Column('edited_by', sa.String(64), nullable=True),
        sa.UniqueConstraint('contract_id','version',name='uq_contract_review_version'))


def downgrade():
    for table in ('contract_review_version', 'contract_source', 'contract_record'):
        if op.get_bind().execute(sa.text(f'SELECT COUNT(*) FROM {table}')).scalar_one():
            raise RuntimeError(f'{table} contains business data; downgrade refused')
    op.drop_table('contract_review_version')
    op.drop_table('contract_source')
    op.drop_table('contract_record')
