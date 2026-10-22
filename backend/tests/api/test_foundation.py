"""Claims and authorization use the isolated database and actual ORM records."""
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.core.context import CurrentUser
from app.core.enums import ErrorCode
from app.core.errors import AppException
from app.db.session import async_session_factory
from app.models.idempotency_record import IdempotencyRecord
from app.schemas.command import CommandEnvelope
from app.services.idempotency_service import claim, complete, resolve_unknown
from app.services.authorization_service import authorize_resource, authorize_tool


def envelope(payload, key):
    return CommandEnvelope(command_id=uuid4(), idempotency_key=key, actor_id="u_emp_001",
                           tenant_id="t_001", resource_type="leave", resource_id="LV-001",
                           trace_id="trace-1", payload=payload)


@pytest.mark.asyncio
async def test_idempotency_same_payload_reuses_saved_result_and_conflicts_on_different_payload(graph_ready):
    key = "idempotent-" + uuid4().hex
    async with async_session_factory() as db:
        async with db.begin():
            first, owned = await claim(db, envelope({"days": 1}, key))
            assert owned
            await complete(db, first, {"status": "submitted", "request_id": "out-1"})
    async with async_session_factory() as db:
        async with db.begin():
            previous, owned = await claim(db, envelope({"days": 1}, key))
            assert not owned
            assert previous.result == {"status": "submitted", "request_id": "out-1"}
            with pytest.raises(AppException) as error:
                await claim(db, envelope({"days": 2}, key))
            assert error.value.code == ErrorCode.IDEMPOTENCY_CONFLICT
    async with async_session_factory() as db:
        records = (await db.scalars(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key))).all()
        assert len(records) == 1


@pytest.mark.asyncio
async def test_uncertain_write_requires_reconciliation_not_second_claim(graph_ready):
    key = "uncertain-" + uuid4().hex
    async with async_session_factory() as db:
        async with db.begin():
            first, _ = await claim(db, envelope({"days": 1}, key))
    async with async_session_factory() as db:
        async with db.begin():
            with pytest.raises(AppException):
                await claim(db, envelope({"days": 1}, key))
            recovered = await resolve_unknown(db, envelope({"days": 1}, key), {"status": "submitted"}, "oa-001")
            assert recovered.status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_tool_permissions_fail_closed_on_revoked_identity_or_tenant():
    actor = CurrentUser(user_id="u_mgr_001", tenant_id="t_001", roles=["approver"], depts=["d_rd"])
    assert authorize_resource(actor, "t_001", "u_emp_001", required_roles={"approver"}).allowed
    assert not authorize_resource(actor, "t_002", "u_emp_001", required_roles={"approver"}).allowed
    with pytest.raises(AppException):
        await authorize_tool(CurrentUser(user_id="u_emp_001", tenant_id="t_001", roles=["employee"], depts=["d_rd"]),
                       "leave", "create_or_update_oa_approval", required_roles={"approver"})


@pytest.mark.asyncio
async def test_permission_refresh_rejects_revoked_role(monkeypatch):
    from app.services import authorization_service
    from app.adapters.oa_adapter import UserContext
    class Identity:
        def get_user_context(self, user_id):
            return UserContext(user_id=user_id, tenant_id="t_001", name="x", dept_id="d_rd", dept_name="研发部", roles=["employee"], data_scope={})
    monkeypatch.setattr(authorization_service, "get_adapter", lambda: Identity())
    actor = CurrentUser(user_id="u_mgr_001", tenant_id="t_001", roles=["approver"], depts=["d_rd"])
    with pytest.raises(AppException):
        await authorization_service.require_fresh_identity(actor, required_roles={"approver"})


@pytest.mark.asyncio
async def test_admin_api_rechecks_live_role_on_each_request(graph_ready):
    import httpx
    from app.main import app as fastapi_app
    from app.adapters.factory import get_adapter
    adapter = get_adapter()
    original = list(adapter._state["users"]["u_admin_001"]["roles"])
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://test") as client:
            headers = {"Authorization": "Bearer mock:u_admin_001"}
            assert (await client.get("/api/admin/agent-policies", headers=headers)).status_code == 200
            adapter._state["users"]["u_admin_001"]["roles"] = ["employee"]
            assert (await client.get("/api/admin/agent-policies", headers=headers)).status_code == 403
    finally:
        adapter._state["users"]["u_admin_001"]["roles"] = original
