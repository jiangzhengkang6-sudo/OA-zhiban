"""B8.2 deny-by-default security gates."""

from unittest.mock import Mock

import pytest

from app.core.context import CurrentUser
from app.core.errors import AppException
from app.services import authorization_service


def test_cross_tenant_resource_is_denied_without_leaking_scope():
    actor = CurrentUser(user_id="u-1", tenant_id="tenant-a", roles=["employee"], depts=["d1"])
    decision = authorization_service.authorize_resource(actor, "tenant-b", "u-1")
    assert decision.allowed is False
    assert decision.reason_code == "forbidden"
    assert decision.resource_scope == {}


async def test_revoked_role_is_rechecked_before_high_impact_tool(monkeypatch):
    monkeypatch.setattr(
        authorization_service,
        "get_adapter",
        lambda: Mock(get_user_context=lambda _: Mock(
            user_id="u-approver", tenant_id="tenant-a", roles=["employee"],
            dept_id="d1", data_scope={},
        )),
    )
    actor = CurrentUser(user_id="u-approver", tenant_id="tenant-a", roles=["approver"], depts=["d1"])
    with pytest.raises(AppException) as exc_info:
        await authorization_service.authorize_tool(
            actor,
            "leave",
            "create_or_update_oa_approval",
            required_roles={"approver"},
        )
    assert exc_info.value.http_status == 403

