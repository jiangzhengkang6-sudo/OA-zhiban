from app.services.policy_version_service import choose_scope, validate_thresholds


def test_choose_scope_uses_user_then_dept_then_tenant_then_global():
    assert choose_scope("user", "dept", "tenant") == ["user", "dept", "tenant", "global"]


def test_validate_thresholds_rejects_negative_and_reversed_values():
    import pytest

    with pytest.raises(ValueError, match="non-negative"):
        validate_thresholds({"nudge_after_seconds": -1})
    with pytest.raises(ValueError, match="escalate"):
        validate_thresholds({"nudge_after_seconds": 20, "escalate_after_seconds": 10})


def test_validate_thresholds_allows_partial_defaults():
    validate_thresholds({"faq_answer_threshold": 0.7})


def test_validate_thresholds_rejects_invalid_canonical_confidence_values():
    import pytest

    with pytest.raises(ValueError, match="faq_answer"):
        validate_thresholds({"faq_answer": 1.1})
