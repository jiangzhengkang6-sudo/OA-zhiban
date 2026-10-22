"""B7 runtime observability API tests."""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from app.db.session import engine
from app.main import app as fastapi_app


@pytest.fixture
async def client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE runtime_span, model_usage RESTART IDENTITY CASCADE"))
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
async def test_operations_metrics_and_trace_drilldown_are_admin_only(client, admin_headers, employee_headers):
    run_id = uuid4()
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO runtime_span (id, tenant_id, trace_id, run_id, node_name, tool_name, started_at, finished_at, duration_ms, status, error_code) "
            "VALUES (:id, 't_001', 'trace-op-1', :run_id, 'classify_intent', NULL, now(), now(), 42, 'success', NULL)"
        ), {"id": str(uuid4()), "run_id": str(run_id)})
        await conn.execute(text(
            "INSERT INTO runtime_span (id, tenant_id, trace_id, run_id, node_name, tool_name, started_at, finished_at, duration_ms, status, error_code) "
            "VALUES (:id, 't_001', 'trace-op-1', :run_id, 'tool_call', 'get_user_context', now(), now(), 18, 'error', '40301')"
        ), {"id": str(uuid4()), "run_id": str(run_id)})
        await conn.execute(text(
            "INSERT INTO model_usage (id, tenant_id, trace_id, run_id, provider, model_name, input_tokens, output_tokens, total_tokens, usage_missing) "
            "VALUES (:id, 't_001', 'trace-op-1', :run_id, 'mock', 'mock-model', NULL, NULL, NULL, true)"
        ), {"id": str(uuid4()), "run_id": str(run_id)})

    metrics = await client.get("/api/operations/metrics?trace_id=trace-op-1", headers=admin_headers)
    assert metrics.status_code == 200
    data = metrics.json()["data"]
    assert data["span_count"] == 2
    assert data["error_count"] == 1
    assert data["usage_missing_count"] == 1
    assert data["total_tokens"] is None

    trace = await client.get("/api/operations/traces/trace-op-1", headers=admin_headers)
    assert trace.status_code == 200
    assert len(trace.json()["data"]["spans"]) == 2
    assert trace.json()["data"]["model_usage"][0]["usage_missing"] is True

    denied = await client.get("/api/operations/metrics", headers=employee_headers)
    assert denied.status_code == 403
