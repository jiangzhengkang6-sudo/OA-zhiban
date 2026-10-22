"""
OA 智能体管理系统 - 对话消息表（agent_message）。

记录会话内消息，仅保存脱敏摘要与内容哈希，敏感敏感字段不落原文（可选 full_content
仅用于非敏感场景，MVP 默认不写敏感原文）。
"""

from typing import Optional

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class AgentMessage(Base, UUIDMixin, TimestampMixin):
    """会话消息。

    Attributes:
        thread_id: 所属会话 ID。
        seq: 会话内消息序号。
        role: 角色（user/assistant/system/tool）。
        content_summary: 脱敏后的内容摘要。
        content_hash: 原文哈希（可追溯但不可反推原文）。
        full_content: 可选完整内容（JSONB，仅非敏感场景）。
    """

    __tablename__ = "agent_message"
    __table_args__ = (Index("ix_agent_message_thread_seq", "thread_id", "seq"),)

    thread_id: Mapped[object] = mapped_column(UUID(as_uuid=True), nullable=False)
    seq: Mapped[int] = mapped_column(nullable=False, default=0)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    full_content: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)