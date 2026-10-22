from typing import Any, Optional

from pydantic import BaseModel, Field


class PolicyVersionCreateRequest(BaseModel):
    scene: str = Field(min_length=1, max_length=16)
    scope_type: str = Field(default="global", pattern=r"^(global|tenant|dept|user)$")
    scope_value: Optional[str] = Field(default=None, max_length=64)
    enabled: bool = True
    thresholds: dict[str, Any] = Field(default_factory=dict)
    rule_version: str = Field(default="v1", max_length=32)
