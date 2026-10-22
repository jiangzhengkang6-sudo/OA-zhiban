"""Stable command scope and canonical payload fingerprint."""
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field, model_validator


class CommandEnvelope(BaseModel):
    command_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=128)
    actor_id: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=64)
    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: str = Field(min_length=1, max_length=128)
    trace_id: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any]
    payload_hash: str = ""
    policy_version: str | None = None

    @model_validator(mode="after")
    def fingerprint(self):
        from ..services.idempotency_service import payload_digest
        digest = payload_digest(self.payload)
        if self.payload_hash and self.payload_hash != digest:
            raise ValueError("命令载荷摘要与实际载荷不一致")
        self.payload_hash = digest
        return self
