import httpx
import pytest
from sqlalchemy import select, text

from app.db.session import async_session_factory, engine
from app.main import app as fastapi_app
from app.models.policy_version import PolicyVersion
from app.services.policy_service import get_thresholds, is_scene_enabled


@pytest.fixture
async def client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE policy_version, agent_policy RESTART IDENTITY CASCADE"))
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def admin_headers():
    return {"Authorization": "Bearer mock:u_admin_001"}


@pytest.mark.asyncio
async def test_policy_publish_is_immutable_and_rollback_creates_new_version(client, admin_headers):
    payload = {"scene": "faq", "scope_type": "global", "enabled": True, "thresholds": {"faq_answer_threshold": 0.6}}
    created = await client.post("/api/admin/agent-policy-versions", json=payload, headers=admin_headers)
    assert created.status_code == 200
    first = created.json()["data"]
    assert first["status"] == "draft"

    published = await client.post(f"/api/admin/agent-policy-versions/{first['id']}/publish", headers=admin_headers)
    assert published.status_code == 200
    assert published.json()["data"]["status"] == "published"

    second = await client.post("/api/admin/agent-policy-versions", json={**payload, "thresholds": {"faq_answer_threshold": 0.8}}, headers=admin_headers)
    second_data = second.json()["data"]
    await client.post(f"/api/admin/agent-policy-versions/{second_data['id']}/publish", headers=admin_headers)

    rollback = await client.post(f"/api/admin/agent-policy-versions/{first['id']}/rollback", headers=admin_headers)
    assert rollback.status_code == 200
    rollback_data = rollback.json()["data"]
    assert rollback_data["version"] == 3
    assert rollback_data["status"] == "published"
    assert rollback_data["thresholds"]["faq_answer_threshold"] == 0.6
    listing = await client.get("/api/admin/agent-policy-versions?scene=faq", headers=admin_headers)
    assert listing.status_code == 200
    assert [row["version"] for row in listing.json()["data"]] == [3, 2, 1]

    async with async_session_factory() as session:
        rows = (await session.execute(select(PolicyVersion).order_by(PolicyVersion.version))).scalars().all()
        assert [row.status for row in rows] == ["offline", "offline", "published"]


@pytest.mark.asyncio
async def test_runtime_policy_reads_published_version_with_scope_precedence(client, admin_headers):
    global_payload = {"scene": "ticket", "scope_type": "global", "enabled": True, "thresholds": {"nudge_after_seconds": 100}}
    user_payload = {"scene": "ticket", "scope_type": "user", "scope_value": "u_emp_001", "enabled": False, "thresholds": {"nudge_after_seconds": 12}}
    for payload in (global_payload, user_payload):
        response = await client.post("/api/admin/agent-policy-versions", json=payload, headers=admin_headers)
        assert response.status_code == 200
        await client.post(f"/api/admin/agent-policy-versions/{response.json()['data']['id']}/publish", headers=admin_headers)

    async with async_session_factory() as session:
        assert await is_scene_enabled(session, "ticket", "u_emp_001", "d_rd", tenant_id="t_001") is False
        thresholds = await get_thresholds(session, "ticket", user_id="u_emp_001", dept_id="d_rd", tenant_id="t_001")
        assert thresholds["nudge_after_seconds"] == 12
