"""Shared mailbox ACL, immutable received sources and durable outgoing intent."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, TimestampMixin


class PublicMailbox(Base, TimestampMixin):
    __tablename__ = 'public_mailbox'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    address: Mapped[str] = mapped_column(String(320), nullable=False)
    config_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    uid_validity: Mapped[str] = mapped_column(String(64), default='', nullable=False)
    last_uid: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class PublicMailboxMember(Base):
    __tablename__ = 'public_mailbox_member'
    mailbox_id: Mapped[str] = mapped_column(ForeignKey('public_mailbox.id'), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    can_process: Mapped[bool] = mapped_column(default=False, nullable=False)
    can_send: Mapped[bool] = mapped_column(default=False, nullable=False)
    can_manage: Mapped[bool] = mapped_column(default=False, nullable=False)


class PublicMailMessage(Base, TimestampMixin):
    __tablename__ = 'public_mail_message'
    __table_args__ = (
        UniqueConstraint('mailbox_id', 'remote_key', name='uq_public_mail_remote'),
        UniqueConstraint('mailbox_id', 'created_by', 'create_key', name='uq_public_mail_create'),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mailbox_id: Mapped[str] = mapped_column(ForeignKey('public_mailbox.id'), index=True, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    remote_key: Mapped[str | None] = mapped_column(String(128))
    message_id: Mapped[str] = mapped_column(String(998), nullable=False)
    sender: Mapped[str] = mapped_column(String(320), nullable=False)
    recipients: Mapped[list] = mapped_column(JSONB, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(64))
    sent_by: Mapped[str | None] = mapped_column(String(64))
    reply_to_id: Mapped[str | None] = mapped_column(ForeignKey('public_mail_message.id'))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    create_key: Mapped[str | None] = mapped_column(String(128))
    create_digest: Mapped[str | None] = mapped_column(String(64))


class PublicMailImport(Base):
    __tablename__ = 'public_mail_import'
    message_id: Mapped[str] = mapped_column(ForeignKey('public_mail_message.id'), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email_id: Mapped[str] = mapped_column(String(64), nullable=False)
