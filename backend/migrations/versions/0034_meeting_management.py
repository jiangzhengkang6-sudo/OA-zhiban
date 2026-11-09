"""Add scheduled meetings without changing existing minutes.

Revision ID: 0034
Revises: 0033
"""
from alembic import op
import sqlalchemy as sa

revision = '0034'
down_revision = '0033'
branch_labels = None
depends_on = None


def upgrade():
    from app.models.oa_meeting import OAMeeting, OAMeetingAttendee
    OAMeeting.__table__.create(op.get_bind(), checkfirst=False)
    OAMeetingAttendee.__table__.create(op.get_bind(), checkfirst=False)


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM oa_meeting')):
        raise RuntimeError('已有会议安排，禁止破坏性降级，请向前修复')
    op.drop_table('oa_meeting_attendee')
    op.drop_table('oa_meeting')
