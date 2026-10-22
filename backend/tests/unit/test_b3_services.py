import pytest

from app.services.handoff_service import redact_context
from app.services.ticket_draft_service import validate_draft_fields
from app.schemas.ticket_draft import TicketDraftUpdate


def test_handoff_redacts_credentials_and_bounds_context():
    payload = redact_context({"token": "secret", "messages": [{"content": "x"}] * 30,
                              "summary": "ok"})
    assert "token" not in payload
    assert len(payload["messages"]) == 20


def test_ticket_draft_rejects_unknown_or_invalid_fields():
    with pytest.raises(ValueError):
        validate_draft_fields({"owner_id": "u-1"})
    with pytest.raises(ValueError):
        TicketDraftUpdate(fields={"priority": "critical"})


def test_ticket_draft_accepts_editable_confirmation_fields():
    assert validate_draft_fields({"priority": "high", "summary": "无法登录"})["priority"] == "high"

