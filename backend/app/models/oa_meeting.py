"""Scheduling and invitations have a separate lifecycle from generated minutes."""
from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base
from .identity import IdentityRow
from .oa_workflow import tenant_key, tenant_fk


class OAMeeting(Base, IdentityRow):
    __tablename__ = 'oa_meeting'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('organizer_id', 'oa_user'),
        tenant_fk('host_id', 'oa_user'), tenant_fk('recorder_id', 'oa_user'),
        UniqueConstraint('tenant_id', 'minutes_id', name='uq_oa_meeting_minutes'),
        CheckConstraint('ends_at > starts_at', name='oa_meeting_time_range'),
        CheckConstraint("state IN ('DRAFT','SCHEDULED','IN_PROGRESS','ENDED','CANCELLED')", name='oa_meeting_state'),
        Index('ix_oa_meeting_calendar', 'tenant_id', 'state', 'starts_at'))
    organizer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    host_id: Mapped[str] = mapped_column(String(64), nullable=False)
    recorder_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    agenda: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False, default='')
    online_url: Mapped[str] = mapped_column(String(2000), nullable=False, default='')
    video_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    video_room_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    state: Mapped[str] = mapped_column(String(24), nullable=False, default='DRAFT')
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    invitation_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    minutes_id: Mapped[str | None] = mapped_column(String(64))
    cancel_reason: Mapped[str] = mapped_column(String(1000), nullable=False, default='')


class OAMeetingAttendee(Base, IdentityRow):
    __tablename__ = 'oa_meeting_attendee'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('meeting_id', 'oa_meeting'),
        tenant_fk('user_id', 'oa_user'), UniqueConstraint('tenant_id', 'meeting_id', 'user_id', name='uq_oa_meeting_attendee'),
        CheckConstraint("response IN ('PENDING','ACCEPTED','DECLINED','TENTATIVE')", name='oa_meeting_response'))
    meeting_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    response: Mapped[str] = mapped_column(String(16), nullable=False, default='PENDING')
    note: Mapped[str] = mapped_column(String(500), nullable=False, default='')
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
