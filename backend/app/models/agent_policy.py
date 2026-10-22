"""
OA 智能体管理系统 - 策略/开关表（agent_policy）。

管理智能路径的场景开关、灰度范围（全局/部门/用户）、阈值与规则版本。变更历史通过
audit_event 追溯（AC-MVP-18），这里只保存当前生效的策略版本。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base, TimestampMixin, UUIDMixin


class AgentPolicy(Base, UUIDMixin, TimestampMixin):
    """智能策略/开关。

    Attributes:
        scene: 场景（leave/faq/ticket/global）。
        scope_type: 作用范围类型（global/dept/user）。
        scope_value: 作用范围值（dept/user 时为具体 ID）。
        enabled: 是否启用。
        thresholds: 阈值配置（JSONB：超时/升级/置信度/转人工）。
        rule_version: 规则版本。
        updated_by: 更新人。
        effective_at: 生效时间。
    """

    __tablename__ = "agent_policy"
    __table_args__ = (
        UniqueConstraint(
            "scene", "scope_type", "scope_value", "rule_version",
            name="uq_agent_policy_scene_scope_version",
        ),
    )

    scene: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    scope_value: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    thresholds: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    effective_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)