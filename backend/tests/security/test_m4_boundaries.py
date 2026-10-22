"""M4 regressions reuse real authorization/transaction boundaries with synthetic data."""
import json
from starlette.requests import Request

from tests.oa_support import oa_db
from tests.security import test_prompt_injection as injection
from tests.api import test_oa_leave_attachments as attachments
from tests.integration import test_oa_approval_transactions as transactions
import pytest


async def test_prompt_cannot_grant_tool_access(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), 'ai_enabled', True)
    monkeypatch.setattr(get_settings(), 'auth_provider', 'mock')
    await injection.test_instruction_like_text_cannot_grant_employee_approval_tool(monkeypatch)


async def test_private_attachment_and_integrity(oa_db, monkeypatch):
    await attachments.test_private_attachment_reference_scan_and_integrity(oa_db, monkeypatch)


@pytest.mark.parametrize('failure', ['event', 'outbox', 'ledger'])
async def test_failed_write_has_no_success_event(oa_db, monkeypatch, failure):
    await transactions.test_last_approval_failure_restores_all_state(oa_db, monkeypatch, failure)


async def test_unhandled_error_does_not_log_sensitive_exception(caplog):
    from app.main import unhandled_exception_handler
    sentinel = 'M4-sensitive-sentinel-7291'
    request = Request({'type':'http', 'method':'GET', 'path':'/', 'headers':[]})
    try:
        raise RuntimeError('Authorization: Bearer ' + sentinel)
    except RuntimeError as error:
        response = await unhandled_exception_handler(request, error)
    assert response.status_code == 500
    assert sentinel not in response.body.decode()
    assert sentinel not in caplog.text
    assert 'RuntimeError' in caplog.text


def test_handoff_sensitive_keys_are_removed_recursively():
    from app.services.handoff_service import redact_context
    sentinel = 'M4-sensitive-sentinel-7291'
    cleaned = redact_context({'summary':'manual review', 'token':sentinel,
        'items':[{'Authorization':sentinel, 'nested':{'password':sentinel, 'secret':sentinel,
            'api_key':sentinel, 'object':'leave'}}]})
    assert sentinel not in json.dumps(cleaned)
    assert cleaned['items'][0]['nested']['object'] == 'leave'
