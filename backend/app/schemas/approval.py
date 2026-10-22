"""
OA 智能体管理系统 - 请假预检请求/响应模型。
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class PrecheckRequest(BaseModel):
    """预检请求（独立入口）。

    Attributes:
        business_id: 业务单据号。
        retry: 是否重试。
    """

    business_id: str
    retry: bool = False


class PrecheckResponse(BaseModel):
    """预检响应。

    Attributes:
        business_id: 业务单据号。
        precheck_result: 逐项预检结果。
        passed: 是否全部通过。
        status: 状态（pass/needs_fix/paused）。
        rule_version: 规则版本。
    """

    business_id: str
    precheck_result: list[dict] = Field(default_factory=list)
    passed: bool = False
    status: str = "needs_fix"
    rule_version: str = "v1"