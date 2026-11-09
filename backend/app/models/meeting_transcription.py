"""Durable cloud transcription commands and tenant-bound final utterances."""
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base
from .identity import IdentityRow
from .oa_workflow import tenant_key, tenant_fk


class MeetingTranscription(Base, IdentityRow):
    __tablename__ = 'meeting_transcription'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('meeting_id', 'oa_meeting'),
        tenant_fk('initiator_id', 'oa_user'), UniqueConstraint('tenant_id', 'meeting_id'),
        UniqueConstraint('robot_id'), UniqueConstraint('task_id'))
    meeting_id: Mapped[str] = mapped_column(String(64), nullable=False)
    initiator_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sdk_app_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    room_id: Mapped[str] = mapped_column(String(64), nullable=False)
    robot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(256))
    state: Mapped[str] = mapped_column(String(24), nullable=False, default='QUEUED', index=True)
    message: Mapped[str] = mapped_column(String(1000), nullable=False, default='')
    partial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stop_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_callback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MeetingUtterance(Base, IdentityRow):
    __tablename__ = 'meeting_utterance'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('transcription_id', 'meeting_transcription'),
        tenant_fk('speaker_id', 'oa_user'), UniqueConstraint('tenant_id', 'transcription_id', 'segment_key'))
    transcription_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    speaker_id: Mapped[str] = mapped_column(String(64), nullable=False)
    segment_key: Mapped[str] = mapped_column(String(64), nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
