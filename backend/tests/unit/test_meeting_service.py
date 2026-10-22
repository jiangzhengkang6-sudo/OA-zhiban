import pytest

from app.services.meeting_service import (
    MeetingStateError,
    apply_decision,
    next_draft_version,
    validate_draft,
)


def test_validate_draft_requires_source_refs_for_decisions_and_actions():
    with pytest.raises(ValueError, match="来源"):
        validate_draft({"summary": "同步", "decisions": [{"text": "确认", "source_refs": []}]})


def test_next_version_never_overwrites_existing_draft():
    assert next_draft_version([]) == 1
    assert next_draft_version([1, 2, 4]) == 5


def test_decision_state_gate_and_rejection_reason():
    assert apply_decision("REVIEWING", "confirm", None) == "CONFIRMED"
    assert apply_decision("REVIEWING", "reject", "内容不完整") == "REJECTED"
    with pytest.raises(MeetingStateError, match="拒绝原因"):
        apply_decision("REVIEWING", "reject", "")
    with pytest.raises(MeetingStateError, match="不可"):
        apply_decision("CONFIRMED", "confirm", None)
