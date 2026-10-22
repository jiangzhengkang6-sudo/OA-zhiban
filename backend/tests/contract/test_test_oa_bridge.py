import importlib

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.oa_adapter import ApprovalCommand, NotificationCommand, TicketCommand
from app.adapters.real_adapter import RealOAAdapter
from app.core.config import Settings

KEY = "test-oa-contract-key"

@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setenv("TEST_OA_API_KEY", KEY)
    module = importlib.import_module("scripts.test_oa_bridge")
    module = importlib.reload(module)
    module.RESULTS = {"approvals": {}, "leave_edits": {}, "tickets": {}, "notifications": {}}
    return module.app

@pytest.fixture
def client(bridge):
    return TestClient(bridge)

def test_auth_and_read_contract(client):
    assert client.get("/capabilities").status_code == 401
    headers = {"Authorization": f"Bearer {KEY}"}
    assert client.get("/capabilities", headers=headers).json()["capabilities"]["identity"] is True
    assert client.get("/users/u_emp_001", headers=headers).json()["dept_id"] == "dept_001"
    assert client.get("/leaves/leave_demo_001", headers=headers).json()["status"] == "PENDING"
    assert client.get("/users/u_emp_001/leave-balance/annual", headers=headers).json()["remaining"] == 12.0
    assert client.get("/leaves/leave_demo_001/approval-route?user_id=u_emp_001", headers=headers).json()["nodes"]

def test_real_adapter_reads_and_writes_with_idempotency(client):
    settings = Settings(_env_file=None, oa_provider="real", oa_base_url="http://test", oa_api_key=KEY)
    def handler(request):
        response = client.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
        return httpx.Response(response.status_code, headers=dict(response.headers), json=response.json())
    adapter = RealOAAdapter(settings=settings, transport=httpx.MockTransport(handler))
    command = ApprovalCommand(business_id="leave_demo_001", idempotency_key="approval-idem-1", action="approve", actor_id="u_manager_001")
    first = adapter.create_or_update_approval(command)
    second = adapter.create_or_update_approval(command)
    assert first.model_dump() == second.model_dump()
    assert adapter.get_approval_result(command.idempotency_key).request_id == first.request_id
    ticket = adapter.create_or_merge_ticket(TicketCommand(idempotency_key="ticket-idem-1", category="it", priority="P2", impact="single_user", summary="demo", user_id="u_emp_001"))
    assert ticket.ticket_id
    note = adapter.notify(NotificationCommand(user_id="u_emp_001", title="demo", body="hello", idempotency_key="notify-idem-1"))
    assert note.delivered is True
    assert adapter.get_notification_result("notify-idem-1").request_id == note.request_id
