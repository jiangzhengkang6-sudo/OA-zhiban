"""Built-in leave attachment metadata; file bytes stay outside the database."""

from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, BigInteger
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class LeaveAttachment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "leave_attachment"
    __table_args__ = (Index("ix_leave_attachment_version", "version_id"),
                      Index("ix_leave_attachment_application", "application_id"))

    version_id: Mapped[UUID | None] = mapped_column(ForeignKey("leave_application_version.id"), nullable=True)
    application_id: Mapped[UUID | None] = mapped_column(ForeignKey("leave_application.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
