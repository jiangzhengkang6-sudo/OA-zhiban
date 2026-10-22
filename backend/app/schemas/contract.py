from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class ContractInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=255)
    reviewer_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=100000)
    idempotency_key: str = Field(min_length=1, max_length=128)


class RiskDisposition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    risk_id: str
    action: Literal['accepted', 'mitigated', 'needs_revision']
    comment: str = Field(min_length=1, max_length=2000)


class ContractCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['review', 'retry', 'save', 'confirm', 'reject', 'rescan']
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_version: int | None = None
    summary: str | None = Field(default=None, min_length=1, max_length=8000)
    dispositions: list[RiskDisposition] = Field(default_factory=list, max_length=100)
    comment: str = Field(default='', max_length=2000)

