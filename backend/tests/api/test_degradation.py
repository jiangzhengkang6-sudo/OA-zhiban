"""B7 degradation control and task policy tests."""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from app.db.session import engine
from app.main import app as fastapi_app


@pytest.fixture
async def client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE degradation_state RESTART IDENTITY CASCADE"))
        await conn.execute(text("TRUNCATE agent_thread RESTART IDENTITY CASCADE"))
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def admin_headers():
    return {"Authorization": "Bearer mock:u_admin_001"}


@pytest.fixture
def employee_headers():
    return {"Authorization": "Bearer mock:u_emp_001"}


@pytest.mark.asyncio
async def test_admin_can_degrade_and_restore_scene(client, admin_headers):
    created = await client.post(
        "/api/operations/degradations",
        headers=admin_headers,
        json={
            "scene": "faq",
            "scope_type": "tenant",
            "scope_value": "t_001",
            "new_task_action": "fallback",
            "inflight_action": "pause",
            "reason": "知识服务维护",
        },
    )
    assert created.status_code == 200
    state = created.json()["data"]
    assert state["enabled"] is True
    assert state["new_task_action"] == "fallback"
    assert state["inflight_action"] == "pause"

    listed = await client.get("/api/operations/degradations", headers=admin_headers)
    assert listed.status_code == 200
    assert listed.json()["data"][0]["reason"] == "知识服务维护"

    restored = await client.post(
        f"/api/operations/degradations/{state['id']}/restore",
        headers=admin_headers,
    )
    assert restored.status_code == 200
    assert restored.json()["data"]["enabled"] is False


@pytest.mark.asyncio
async def test_degradation_is_admin_only(client, employee_headers):
    response = await client.post(
        "/api/operations/degradations",
        headers=employee_headers,
        json={"scene": "faq", "reason": "x"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_new_request_falls_back_without_invoking_graph(client, admin_headers, employee_headers):
    await client.post(
        "/api/operations/degradations",
        headers=admin_headers,
        json={"scene": "faq", "scope_type": "tenant", "scope_value": "t_001", "reason": "维护"},
    )
    created = await client.post("/api/agent/threads", headers=employee_headers, json={"scene": "faq"})
    assert created.status_code == 200
    thread_id = created.json()["data"]["thread_id"]
    response = await client.post(
        f"/api/agent/threads/{thread_id}/messages",
        headers=employee_headers,
        json={"content": "请查询制度", "idempotency_key": str(uuid4())},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "WAITING_HUMAN"
    assert response.json()["data"]["next_action"] == "human"


@pytest.mark.asyncio
async def test_inflight_task_can_be_paused_by_degradation(client, admin_headers, employee_headers):
    created = await client.post("/api/agent/threads", headers=employee_headers, json={"scene": "faq"})
    thread_id = created.json()["data"]["thread_id"]
    await client.post(
        "/api/operations/degradations",
        headers=admin_headers,
        json={"scene": "faq", "scope_type": "tenant", "scope_value": "t_001", "inflight_action": "pause", "reason": "维护"},
    )
    response = await client.post(
        f"/api/agent/threads/{thread_id}/messages",
        headers=employee_headers,
        json={"content": "继续处理", "idempotency_key": str(uuid4())},
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "PAUSED"
