import pytest
from pydantic import ValidationError

from app.schemas.document import DocumentInput
from app.services.document_templates import TEMPLATES, check_document


def test_templates_are_versioned_and_cover_four_kinds():
    assert {item.kind for item in TEMPLATES.values()} == {"official", "notice", "report", "summary"}
    assert all(item.version == 1 and item.sections for item in TEMPLATES.values())


@pytest.mark.parametrize("field", ["subject", "recipient", "distribution", "key_points"])
def test_input_rejects_blank_required_fields(field):
    payload = dict(template_id="notice", subject="验收通知", recipient="项目组", distribution="项目组内部", key_points="周五验收", idempotency_key="test-create")
    payload[field] = "  "
    with pytest.raises(ValidationError):
        DocumentInput(**payload)


def test_checks_block_missing_sections_and_placeholders_without_leaking_sensitive_values():
    issues = check_document("[待补充]\n联系电话：13800138000", TEMPLATES["notice"])
    assert any(item.severity == "error" for item in issues)
    assert any(item.code == "SENSITIVE_DATA" for item in issues)
    assert "13800138000" not in str([item.model_dump() for item in issues])


def test_complete_notice_has_no_blocking_issues():
    body = "\n".join(f"## {heading}\n验收安排请按计划完成。" for heading in TEMPLATES["notice"].sections)
    assert not check_document(body, TEMPLATES["notice"])
