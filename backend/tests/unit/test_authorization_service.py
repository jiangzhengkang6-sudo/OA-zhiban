from unittest.mock import Mock
import pytest
from app.core.context import CurrentUser
from app.core.errors import AppException
from app.services.authorization_service import authorize_resource, authorize_tool, require_fresh_identity


def actor(role="employee", tenant="t_001"):
    return CurrentUser(user_id="u_emp_001", tenant_id=tenant, roles=[role], depts=["d_rd"])


def test_owner_only_within_tenant():
    assert authorize_resource(actor(), "t_001", "u_emp_001").allowed
    assert not authorize_resource(actor(), "t_002", "u_emp_001").allowed
    assert not authorize_resource(actor(), "t_001", "u_emp_002").allowed


async def test_static_tool_allowlist_cannot_be_overridden_by_policy():
    with pytest.raises(AppException):
        await authorize_tool(actor(), "faq", "create_or_update_oa_approval", policy_tools=["create_or_update_oa_approval"])


async def test_policy_can_restrict_but_not_grant():
    with pytest.raises(AppException):
        await authorize_tool(actor(), "ticket", "create_or_merge_ticket", policy_tools=["get_ticket_status"])


async def test_fresh_identity_rejects_cross_tenant(monkeypatch):
    from app.services import authorization_service
    monkeypatch.setattr(authorization_service, "get_adapter", lambda: Mock(get_user_context=lambda _: Mock(tenant_id="t_002", roles=["employee"], dept_id="d_rd", data_scope={})))
    with pytest.raises(AppException):
        await require_fresh_identity(actor())
