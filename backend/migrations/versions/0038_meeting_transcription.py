"""Cloud transcription ledger and final utterances; no audio/video storage."""
from alembic import op
import sqlalchemy as sa

revision = '0038'
down_revision = '0037'
branch_labels = None
depends_on = None


def identity():
    return [sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def upgrade():
    op.create_table('meeting_transcription', *identity(),
        sa.Column('meeting_id', sa.String(64), nullable=False),
        sa.Column('initiator_id', sa.String(64), nullable=False),
        sa.Column('sdk_app_id', sa.BigInteger(), nullable=False),
        sa.Column('room_id', sa.String(64), nullable=False),
        sa.Column('robot_id', sa.String(64), nullable=False, unique=True),
        sa.Column('task_id', sa.String(256), unique=True),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('message', sa.String(1000), nullable=False),
        sa.Column('partial', sa.Boolean(), nullable=False),
        *[sa.Column(name, sa.DateTime(timezone=True)) for name in
            ['stop_requested_at','stopped_at','last_callback_at','frozen_at','next_attempt_at']],
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.UniqueConstraint('tenant_id','id',name='uq_meeting_transcription_tenant_identity'),
        sa.UniqueConstraint('tenant_id','meeting_id'),
        sa.ForeignKeyConstraint(['tenant_id','meeting_id'],['oa_meeting.tenant_id','oa_meeting.id']),
        sa.ForeignKeyConstraint(['tenant_id','initiator_id'],['oa_user.tenant_id','oa_user.id']))
    op.create_index('ix_meeting_transcription_state','meeting_transcription',['state'])
    op.create_table('meeting_utterance', *identity(),
        sa.Column('transcription_id', sa.String(64), nullable=False),
        sa.Column('speaker_id', sa.String(64), nullable=False),
        sa.Column('segment_key', sa.String(64), nullable=False),
        sa.Column('start_ms', sa.BigInteger(), nullable=False),
        sa.Column('end_ms', sa.BigInteger(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.UniqueConstraint('tenant_id','id',name='uq_meeting_utterance_tenant_identity'),
        sa.UniqueConstraint('tenant_id','transcription_id','segment_key'),
        sa.ForeignKeyConstraint(['tenant_id','transcription_id'],['meeting_transcription.tenant_id','meeting_transcription.id']),
        sa.ForeignKeyConstraint(['tenant_id','speaker_id'],['oa_user.tenant_id','oa_user.id']))
    op.create_index('ix_meeting_utterance_transcription_id','meeting_utterance',['transcription_id'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM meeting_transcription')):
        raise RuntimeError('请保留转写审计记录，使用前向修复或备份恢复')
    op.drop_table('meeting_utterance')
    op.drop_table('meeting_transcription')
