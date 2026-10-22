"""B7 controlled audit export API tests."""

import json

import httpx
import pytest
from sqlalchemy import text

from app.db.session import engine
from app.main import app as fastapi_app


@pytest.fixture
async def client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE audit_event RESTART IDENTITY CASCADE"))
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def admin_headers():
    return {"Authorization": "Bearer mock:u_admin_001"}


@pytest.fixture
def employee_headers():
    return {"Authorization": "Bearer mock:u_emp_001"}


async def _seed_events(client, admin_headers):
    await client.post(
        "/api/audit/exports",
        json={"business_id": "B-100", "page_size": 100},
        headers=admin_headers,
    )
    # The export action above is intentionally not part of the business filter.
    await client.get("/api/audit/events", headers=admin_headers)


@pytest.mark.asyncio
async def test_audit_export_is_role_scoped_and_redacts_sensitive_summaries(
    client, admin_headers, employee_headers
):
    denied = await client.post(
        "/api/audit/exports",
        json={},
        headers=employee_headers,
    )
    assert denied.status_code == 403

    created = await client.post(
        "/api/audit/exports",
        json={
            "business_id": "B-100",
            "action": "tool_called",
            "page_size": 100,
        },
        headers=admin_headers,
    )
    assert created.status_code == 200
    export = created.json()["data"]
    assert export["status"] == "completed"
    assert export["row_count"] == 0

    details = await client.get(
        f"/api/audit/exports/{export['id']}", headers=admin_headers
    )
    assert details.status_code == 200
    assert details.json()["data"]["download_url"].endswith("/download")


@pytest.mark.asyncio
async def test_audit_export_matches_filtered_events_and_records_export_audit(
    client, admin_headers
):
    # Seed directly so the export audit event does not match the business filter.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_event"
                " (trace_id, business_id, actor_id, action, input_summary, output_summary, result)"
                " VALUES ('trace-1', 'B-200', 'u_emp_001', 'tool_called',"
                " '{\"authorization\":\"Bearer secret\",\"normal\":\"ok\"}',"
                " '{\"api_key\":\"top-secret\",\"answer\":\"done\"}', 'success')"
            )
        )

    created = await client.post(
        "/api/audit/exports",
        json={"business_id": "B-200", "action": "tool_called"},
        headers=admin_headers,
    )
    assert created.status_code == 200
    export = created.json()["data"]
    assert export["row_count"] == 1

    download = await client.get(
        f"/api/audit/exports/{export['id']}/download", headers=admin_headers
    )
    assert download.status_code == 200
    payload = json.loads(download.content)
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["business_id"] == "B-200"
    assert item["input_summary"]["authorization"] == "***REDACTED***"
    assert item["output_summary"]["api_key"] == "***REDACTED***"

    events = await client.get(
        "/api/audit/events?action=audit_export_created", headers=admin_headers
    )
    assert events.status_code == 200
    assert events.json()["data"]["total"] == 1
