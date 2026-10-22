"""
OA 智能体管理系统 - 审计事件表（audit_event）。

合规审计核心表：记录会话/路由/工具调用/预检/检索/模型回答/人工决定/业务写入/通知/
重试/异常/配置变更/降级等事件。高写入量使用 bigserial 自增主键，仅存摘要与哈希，
不落敏感原文。支持按 trace_id / thread_id / business_id / actor / action 检索。
"""

from typing import Optional

from sqlalchemy import Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin


class AuditEvent(Base, TimestampMixin):
    """审计事件。

    Attributes:
        trace_id: 一次运行全局追踪 ID。
        thread_id: 关联会话 ID（软关联，可空）。
        business_id: 冗余业务单据号（便于按单据检索）。
        actor_id: 操作者 ID。
        action: 事件动作（见 AuditAction）。
        target_type: 目标类型。
        target_id: 目标 ID。
        tool_name: 工具名（工具调用事件）。
        input_summary: 输入摘要（脱敏 JSONB）。
        output_summary: 输出摘要（脱敏 JSONB）。
        result: 结果（success/fail）。
        error_code: 错误码。
        policy_version: 策略版本。
        duration_ms: 耗时（毫秒）。
    """

    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_trace", "trace_id"),
        Index("ix_audit_thread", "thread_id"),
        Index("ix_audit_actor_created", "actor_id", "created_at"),
        Index("ix_audit_action", "action"),
        Index("ix_audit_business", "business_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    trace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    thread_id: Mapped[Optional[object]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    business_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    input_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    result: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    policy_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)