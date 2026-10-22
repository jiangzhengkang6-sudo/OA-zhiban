"""
OA 智能体管理系统 - 会话/任务主表（agent_thread）。

该表是智能编排层的主锚点：id 同时充当 LangGraph Checkpointer 的 thread_id，
实现"一条主线对账"。business_id 仅作为幂等键与 OA 单据对账外键存在。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class AgentThread(Base, UUIDMixin, TimestampMixin):
    """智能体会话与任务主表。

    Attributes:
        user_id: OA 用户 ID。
        tenant_id: 租户 ID。
        scene: 业务场景（leave/faq/ticket）。
        status: 编排状态（见 ThreadStatus）。
        intent: 识别到的意图（见 Intent）。
        business_id: OA 业务单据号（幂等/对账）。
        current_interrupt_id: 当前 pending 的 HITL 中断 ID。
        waiting_since: 进入等待人工的时间（催办扫描用）。
        last_nudge_at: 上次催办时间。
        escalated_at: 升级时间。
        policy_version: 生效策略版本快照。
        error_code: 暂停/失败错误码。
        error_msg: 暂停/失败描述。
    """

    __tablename__ = "agent_thread"
    __table_args__ = (
        Index("ix_agent_thread_user_created", "user_id", "created_at"),
        Index("ix_agent_thread_status_waiting", "status", "waiting_since"),
        Index("ix_agent_thread_business", "business_id"),
    )

    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scene: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    intent: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    business_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    current_interrupt_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    waiting_since: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_nudge_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    escalated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    policy_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)