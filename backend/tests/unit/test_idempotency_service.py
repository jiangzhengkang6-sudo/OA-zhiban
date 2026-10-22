from uuid import uuid4
import pytest
from app.schemas.command import CommandEnvelope
from app.services.idempotency_service import payload_digest


def envelope(payload, key="submit-1"):
    return CommandEnvelope(
        command_id=uuid4(), idempotency_key=key, actor_id="u_emp_001", tenant_id="t_001",
        resource_type="leave", resource_id="LV-001", payload=payload, trace_id="trace-1",
    )


def test_digest_is_canonical_and_sensitive_payload_is_not_stored():
    first = envelope({"b": 2, "a": "secret"})
    second = envelope({"a": "secret", "b": 2})
    assert first.payload_hash == second.payload_hash == payload_digest(first.payload)
    assert "secret" not in first.payload_hash


def test_empty_scopes_cannot_be_claimed():
    with pytest.raises(ValueError):
        envelope({"a": 1}, key="")

