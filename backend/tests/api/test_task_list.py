"""B4 Task Center API contract tests."""

import httpx
import pytest
from sqlalchemy import text

from app.db.session import engine
from app.main import app as fastapi_app


@pytest.fixture
async def client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE agent_thread, agent_message, precheck_result, human_decision, "
            "ticket_record, ticket_assignment_rule, ticket_context, audit_event, agent_policy, policy_version, knowledge_chunk, knowledge_document, "
            "approval_decision, approval_node, approval_instance, human_queue_item, "
            "handoff_snapshot, ticket_draft RESTART IDENTITY CASCADE"
        ))
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def emp_headers():
    return {"Authorization": "Bearer mock:u_emp_001"}


@pytest.fixture
def mgr_headers():
    return {"Authorization": "Bearer mock:u_mgr_001"}


@pytest.mark.asyncio
async def test_task_list_returns_structured_owned_tasks_with_filters(client, emp_headers):
    created = await client.post(
        "/api/agent/threads", json={"scene": "ticket"}, headers=emp_headers
    )
    tid = created.json()["data"]["thread_id"]
    await client.post(
        f"/api/agent/threads/{tid}/messages",
        json={"content": "我的电脑无法开机"}, headers=emp_headers,
    )

    response = await client.get("/api/tasks?scene=ticket&status=WAITING_HUMAN&page=1&page_size=1",
                                headers=emp_headers)
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["page"] == 1
    assert payload["page_size"] == 1
    assert payload["total"] == 1
    task = payload["items"][0]
    assert task["task_id"] == tid
    assert task["task_type"] == "ticket"
    assert task["business_status"] == "WAITING_HUMAN"
    assert task["next_action"] == "human"
    assert task["responsibility"]["role"] == "owner"
    assert "continue" in task["available_actions"]


@pytest.mark.asyncio
async def test_approver_task_list_contains_only_current_approval_scope(client, emp_headers, mgr_headers):
    created = await client.post(
        "/api/agent/threads",
        json={"scene": "leave", "business_id": "LV-OK-001"},
        headers=emp_headers,
    )
    tid = created.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages",
                      json={"content": "提交请假申请"}, headers=emp_headers)

    response = await client.get("/api/tasks?scene=leave&status=WAITING_HUMAN", headers=mgr_headers)
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    current = next(item for item in items if item["task_id"] == tid)
    assert current["responsibility"]["user_id"] == "u_mgr_001"
    assert {"approve", "edit", "reject"}.issubset(current["available_actions"])

    detail = await client.get(f"/api/tasks/{tid}", headers=mgr_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["task_id"] == tid


@pytest.mark.asyncio
async def test_task_list_rejects_unrelated_tenant_or_user(client, emp_headers):
    created = await client.post(
        "/api/agent/threads", json={"scene": "ticket"}, headers=emp_headers
    )
    tid = created.json()["data"]["thread_id"]
    response = await client.get(f"/api/tasks/{tid}",
                                headers={"Authorization": "Bearer mock:u_cs_001"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_task_handoff_and_unsupported_retry_are_structured(client, emp_headers):
    created = await client.post(
        "/api/agent/threads", json={"scene": "ticket"}, headers=emp_headers
    )
    tid = created.json()["data"]["thread_id"]
    await client.post(f"/api/agent/threads/{tid}/messages",
                      json={"content": "账号无法登录"}, headers=emp_headers)

    handed = await client.post(f"/api/tasks/{tid}/handoff", headers=emp_headers)
    assert handed.status_code == 200
    assert handed.json()["data"]["business_status"] == "WAITING_HUMAN"

    retry = await client.post(f"/api/tasks/{tid}/retry", headers=emp_headers)
    assert retry.status_code == 422


@pytest.mark.asyncio
async def test_inbox_filter_excludes_owned_nonapproval_tasks_before_pagination(client, emp_headers):
    await client.post('/api/agent/threads', json={'scene': 'ticket'}, headers=emp_headers)
    response = await client.get('/api/tasks?inbox=true&page_size=1', headers=emp_headers)
    assert response.status_code == 200
    assert response.json()['data']['total'] == 0
    assert response.json()['data']['items'] == []
