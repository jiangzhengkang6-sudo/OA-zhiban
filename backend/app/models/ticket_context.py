"""
OA 智能体管理系统 - 工单上下文表（ticket_context）。

记录工单的抽取字段、状态、队列/责任人及合并信息，作为智能层工单业务数据的权威快照
（与 OA 工单系统对账）。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class TicketContext(Base, UUIDMixin, TimestampMixin):
    """工单上下文。

    Attributes:
        ticket_id: 工单号（唯一）。
        thread_id: 来源会话 ID。
        category: 类别。
        priority: 优先级。
        impact: 影响范围。
        summary: 问题摘要。
        extracted_fields: 抽取字段（JSONB）。
        status: 工单状态。
        queue_id: 队列 ID。
        assignee_id: 责任人 ID。
        merged_from: 合并来源（JSONB）。
        feedback: 用户反馈（resolved/needs_help）。
    """

    __tablename__ = "ticket_context"
    __table_args__ = (Index("ix_ticket_assignee_status", "assignee_id", "status"),)

    ticket_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    thread_id: Mapped[object] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    priority: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    impact: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_fields: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    queue_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    assignee_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    merged_from: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    feedback: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # 最近处理进度时间
    last_updated_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True
    )