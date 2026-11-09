"""Department announcements and explicit in-app reading receipts."""
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base
from .identity import IdentityRow
from .oa_workflow import tenant_key, tenant_fk


class OAAnnouncement(Base, IdentityRow):
    __tablename__ = 'oa_announcement'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('department_id', 'oa_department'),
        tenant_fk('author_id', 'oa_user'), CheckConstraint('revision >= 1', name='announcement_revision'),
        CheckConstraint("state IN ('DRAFT','PUBLISHED','WITHDRAWN')", name='announcement_state'))
    department_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    author_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default='DRAFT')
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAAnnouncementRead(Base, IdentityRow):
    __tablename__ = 'oa_announcement_read'
    __table_args__ = (tenant_key(__tablename__), tenant_fk('announcement_id', 'oa_announcement'),
        tenant_fk('reader_id', 'oa_user'), UniqueConstraint('tenant_id', 'announcement_id', 'reader_id'))
    announcement_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reader_id: Mapped[str] = mapped_column(String(64), nullable=False)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
