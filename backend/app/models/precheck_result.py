"""
OA 智能体管理系统 - 预检结果表（precheck_result）。

记录请假预检的逐项结果，每项携带通过/失败、原因、证据与修改建议，供审批卡片与
审计查询使用。
"""

from typing import Optional

from sqlalchemy import Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class PrecheckResult(Base, UUIDMixin, TimestampMixin):
    """请假预检结果项。

    Attributes:
        thread_id: 所属会话 ID。
        business_id: 业务单据号。
        rule_version: 预检规则版本。
        item: 检查项（field/attachment/balance/conflict）。
        result: 判定结果（pass/fail）。
        reason: 通过/失败原因。
        evidence: 证据（JSONB）。
        suggestion: 修改建议。
    """

    __tablename__ = "precheck_result"
    __table_args__ = (
        Index("ix_precheck_business_version", "business_id", "rule_version"),
        Index("ix_precheck_thread", "thread_id"),
    )

    thread_id: Mapped[object] = mapped_column(UUID(as_uuid=True), nullable=False)
    business_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    rule_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    item: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    suggestion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)