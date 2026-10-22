"""
OA 智能体管理系统 - 策略配置请求/响应模型。
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class PolicyUpdateRequest(BaseModel):
    """策略更新请求。

    Attributes:
        scene: 场景（leave/faq/ticket/global）。
        scope_type: 作用范围类型（global/dept/user）。
        scope_value: 作用范围值。
        enabled: 是否启用。
        thresholds: 阈值配置。
        rule_version: 规则版本。
    """

    scene: str
    scope_type: str = "global"
    scope_value: Optional[str] = None
    enabled: bool = True
    thresholds: dict[str, Any] = Field(default_factory=dict)
    rule_version: str = "v1"


class PolicyOut(BaseModel):
    """策略响应。

    Attributes:
        scene: 场景。
        scope_type: 作用范围类型。
        scope_value: 作用范围值。
        enabled: 是否启用。
        thresholds: 阈值。
        rule_version: 规则版本。
        updated_by: 更新人。
    """

    scene: str
    scope_type: str
    scope_value: Optional[str] = None
    enabled: bool
    thresholds: dict[str, Any] = Field(default_factory=dict)
    rule_version: str
    updated_by: Optional[str] = None