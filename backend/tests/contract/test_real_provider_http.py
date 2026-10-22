"""Contract tests for the configurable real OA HTTP provider."""

import httpx
import pytest

from app.adapters.oa_adapter import ApprovalCommand, LeaveCase, LeaveEditCommand
from app.adapters.real_adapter import RealOAAdapter
from app.core.config import Settings
from app.core.errors import AppException


def make_adapter(handler):
    settings = Settings(
        _env_file=None,
        oa_provider="real",
        oa_base_url="https://oa.example.test/api",
        oa_api_key="secret-token",
        oa_read_retries=2,
    )
    return RealOAAdapter(settings=settings, transport=httpx.MockTransport(handler))


def test_real_provider_sends_auth_and_maps_user_context():
    def handler(request: httpx.Request):
        assert request.url.path == "/api/users/u-1"
        assert request.headers["Authorization"] == "Bearer secret-token"
        return httpx.Response(200, json={"user_id": "u-1", "tenant_id": "t-1", "name": "张三", "dept_id": "d-1", "dept_name": "研发", "roles": ["employee"]})

    user = make_adapter(handler).get_user_context("u-1")
    assert user.tenant_id == "t-1"
    assert user.roles == ["employee"]


def test_real_provider_retries_read_only_requests():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, json={"message": "busy"})
        return httpx.Response(200, json={"leave_type": "annual", "total": 10, "used": 1, "remaining": 9, "unit": "day"})

    balance = make_adapter(handler).get_leave_balance("u-1", "annual")
    assert calls == 3
    assert balance.remaining == 9


def test_real_provider_does_not_retry_non_transient_read_errors():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"message": "bad request"})

    with pytest.raises(AppException) as exc_info:
        make_adapter(handler).get_user_context("u-1")
    assert calls == 1
    assert exc_info.value.http_status == 502
    assert exc_info.value.detail["status_code"] == 400


def test_real_provider_write_has_idempotency_and_does_not_retry():
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        assert request.method == "POST"
        assert request.headers["Idempotency-Key"] == "idem-1"
        return httpx.Response(503, json={"message": "busy"})

    command = ApprovalCommand(business_id="LV-1", idempotency_key="idem-1", action="approve", actor_id="u-2")
    with pytest.raises(AppException) as exc_info:
        make_adapter(handler).create_or_update_approval(command)
    assert calls == 1
    assert exc_info.value.http_status == 502


def test_real_provider_capability_probe_is_explicit_and_fail_closed():
    def handler(request: httpx.Request):
        assert request.url.path == "/api/capabilities"
        return httpx.Response(200, json={"capabilities": {"identity": True, "leave_read": True, "approval_write": True}})

    capabilities = make_adapter(handler).probe_capabilities()
    assert capabilities.identity
    assert capabilities.leave_read
    assert capabilities.approval_write


def test_reconciliation_returns_none_only_for_authoritative_not_found():
    def not_found(request: httpx.Request):
        return httpx.Response(404, json={"message": "not recorded"})

    assert make_adapter(not_found).get_approval_result("idem-404") is None

    def unavailable(request: httpx.Request):
        return httpx.Response(503, json={"message": "unavailable"})

    with pytest.raises(AppException) as exc_info:
        make_adapter(unavailable).get_approval_result("idem-503")
    assert exc_info.value.http_status == 502
    assert exc_info.value.detail["status_code"] == 503


def test_identifiers_are_encoded_before_becoming_paths():
    def handler(request: httpx.Request):
        # HTTPX exposes a decoded URL path; raw_path is the wire-level assertion.
        assert request.url.path.endswith("/users/user/with/slash")
        assert request.url.raw_path.endswith(b"/users/user%2Fwith%2Fslash")
        return httpx.Response(200, json={"user_id": "user/with/slash", "tenant_id": "t-1", "name": "A", "dept_id": "d-1", "dept_name": "D"})

    assert make_adapter(handler).get_user_context("user/with/slash").user_id == "user/with/slash"


def test_write_identifiers_are_encoded_before_becoming_paths():
    def handler(request: httpx.Request):
        assert request.method == "POST"
        assert request.url.raw_path.startswith(b"/api/leaves/LV%2Fwith%2Fslash/edit")
        return httpx.Response(200, json={"success": True, "request_id": "req-1", "idempotency_key": "edit-1"})

    command = LeaveEditCommand(
        business_id="LV/with/slash",
        idempotency_key="edit-1",
        actor_id="u-1",
        expected_form=LeaveCase(
            business_id="LV/with/slash",
            user_id="u-1",
            leave_type="annual",
            start_at="2026-10-14T09:00:00Z",
            end_at="2026-10-14T18:00:00Z",
            reason="old",
        ),
        fields={"reason": "updated"},
    )
    assert make_adapter(handler).edit_leave_case(command).success is True
