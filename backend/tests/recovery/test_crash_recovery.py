"""B8.2 recovery invariants for uncertain external writes."""

import httpx
import pytest

from app.adapters.oa_adapter import ApprovalCommand
from app.adapters.real_adapter import RealOAAdapter
from app.core.config import Settings
from app.core.errors import AppException


def test_write_timeout_is_not_retried_and_can_only_be_reconciled_by_key():
    writes = 0

    def handler(request: httpx.Request):
        nonlocal writes
        writes += 1
        raise httpx.ReadTimeout("response lost")

    adapter = RealOAAdapter(
        settings=Settings(_env_file=None, oa_provider="real", oa_base_url="https://oa.example.test/api", oa_api_key="secret"),
        transport=httpx.MockTransport(handler),
    )
    command = ApprovalCommand(business_id="LV-1", idempotency_key="approval-1", action="approve", actor_id="u-2")
    with pytest.raises(AppException) as exc_info:
        adapter.create_or_update_approval(command)
    assert writes == 1
    assert exc_info.value.http_status == 502

