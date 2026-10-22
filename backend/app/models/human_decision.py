"""
OA 智能体管理系统 - 人工决定表（human_decision）。

记录所有 HITL 人工决定（审批人 approve/edit/reject、用户 confirm/cancel、系统
escalate），每次决定必须携带操作者与时间；payload_hash 用于防篡改校验。
"""

from typing import Optional

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class HumanDecision(Base, UUIDMixin, TimestampMixin):
    """人工决定记录。

    Attributes:
        thread_id: 所属会话 ID。
        interrupt_id: 对应的 HITL 中断 ID。
        actor_id: 决策操作者 ID。
        action: 动作（approve/edit/reject/confirm/cancel/escalate）。
        comment: 决策意见。
        edited_data: 编辑后的数据（edit 动作时）。
        payload_hash: 决策载荷哈希（防篡改）。
    """

    __tablename__ = "human_decision"
    __table_args__ = (
        Index("ix_human_decision_thread", "thread_id"),
        Index("ix_human_decision_actor_created", "actor_id", "created_at"),
    )

    thread_id: Mapped[object] = mapped_column(UUID(as_uuid=True), nullable=False)
    interrupt_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    edited_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    payload_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)