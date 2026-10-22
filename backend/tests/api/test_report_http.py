"""Report confirmation, SQL isolation, snapshot evidence and live scope tests."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db.session import async_session_factory, engine
from app.main import app
from app.models.agent_thread import AgentThread
from app.models.report_record import ReportRecord, ReportVersion
from app.models.ticket_record import TicketRecord
from app.models.approval_instance import ApprovalInstance
from app.models.work_task import WorkTask
from app.models.work_task_batch import WorkTaskBatch
from app.services import report_query, report_generator

EMP = {"Authorization": "Bearer mock:u_emp_001"}
MGR = {"Authorization": "Bearer mock:u_mgr_001"}
ADMIN = {"Authorization": "Bearer mock:u_admin_001"}


@pytest.fixture
async def report_client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE agent_thread, report_record, ticket_record, approval_instance, work_task, "
            "idempotency_record, audit_event, runtime_span, agent_policy, policy_version, degradation_state RESTART IDENTITY CASCADE"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def create(client, *, key="report-create", metrics=None, scope="own", headers=EMP):
    response = await client.post("/api/reports", headers=headers, json={"subject": "周运营报告", "idempotency_key": key,
        "plan": {"metrics": metrics or ["ticket_volume"], "start": "2026-10-01", "end": "2026-10-08", "scope": scope}})
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def approve(client, record, key="approve", headers=EMP):
    response = await client.post(f"/api/reports/{record['report_id']}/approve-plan", headers=headers,
        json={"expected_version": record["version"], "plan_confirmed": True, "idempotency_key": key})
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def seed_tickets():
    async with async_session_factory() as session:
        for index, (tenant, owner, created) in enumerate([
            ("t_001", "u_emp_001", datetime(2026, 9, 30, 16, tzinfo=timezone.utc)),
            ("t_001", "u_emp_001", datetime(2026, 10, 6, 16, tzinfo=timezone.utc)),
            ("t_001", "u_emp_001", datetime(2026, 10, 7, 16, tzinfo=timezone.utc)),
            ("t_001", "u_emp_001", datetime(2026, 9, 25, 16, tzinfo=timezone.utc)),
            ("t_001", "u_mgr_001", datetime(2026, 10, 2, 16, tzinfo=timezone.utc)),
            ("another-tenant", "u_emp_001", datetime(2026, 10, 2, 16, tzinfo=timezone.utc)),
        ]):
            session.add(TicketRecord(tenant_id=tenant, user_id=owner, ticket_id=f"RPT-TKT-{index}",
                category="other", priority="medium", impact="individual", summary="private source body",
                status="open", created_at=created, idempotency_key=f"seed-{index}", payload_hash="seed"))
        await session.commit()


@pytest.mark.asyncio
async def test_report_approved_plan_exact_numbers_boundary_scope_and_immutable_publish(report_client, monkeypatch):
    await seed_tickets()
    query = AsyncMock(wraps=report_query.execute_plan)
    monkeypatch.setattr(report_query, "execute_plan", query)
    record = await create(report_client)
    query.assert_not_called()
    assert record["status"] == "PLAN_READY" and record["snapshot"] is None
    missing = await report_client.post(f"/api/reports/{record['report_id']}/approve-plan", headers=EMP,
        json={"idempotency_key": "missing", "expected_version": 1})
    assert missing.status_code == 422
    query.assert_not_called()
    generated = await approve(report_client, record)
    metric = generated["snapshot"]["metrics"][0]
    assert (metric["current"], metric["previous"], metric["change_percent"]) == (2, 1, 100.0)
    assert sum(item["value"] for item in metric["buckets"]) == 2
    assert metric["buckets"][0] == {"day": "2026-10-01", "value": 1}
    assert generated["status"] == "DRAFT_READY"
    assert "private source body" not in str(generated)
    assert "source_ids" not in str(generated)
    replay = await approve(report_client, record)
    assert replay == generated and query.await_count == 1
    draft = {**generated["draft"], "summary": generated["draft"]["summary"] + " 请继续核查。"}
    response = await report_client.patch(f"/api/reports/{record['report_id']}/draft", headers=EMP,
        json={"idempotency_key": "edit", "expected_version": 2, "draft": draft})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["version"] == 3
    stale = await report_client.post(f"/api/reports/{record['report_id']}/publish", headers=EMP,
        json={"idempotency_key": "stale", "expected_version": 2, "definitions_confirmed": True, "causes_acknowledged": True})
    assert stale.status_code == 409
    publication = await report_client.post(f"/api/reports/{record['report_id']}/publish", headers=EMP,
        json={"idempotency_key": "publish", "expected_version": 3, "definitions_confirmed": True, "causes_acknowledged": True})
    assert publication.status_code == 200, publication.text
    assert publication.json()["data"]["status"] == "PUBLISHED"
    assert publication.json()["data"]["external_writes"] is False
    terminal = await report_client.patch(f"/api/reports/{record['report_id']}/draft", headers=EMP,
        json={"idempotency_key": "terminal", "expected_version": 3, "draft": draft})
    assert terminal.status_code == 422
    versions = await report_client.get(f"/api/reports/{record['report_id']}/versions", headers=EMP)
    assert [version["version"] for version in versions.json()["data"]] == [2, 3]
    assert versions.json()["data"][0]["snapshot"] == versions.json()["data"][1]["snapshot"]


@pytest.mark.asyncio
async def test_report_empty_results_private_access_and_unregistered_sql(report_client):
    record = await create(report_client, metrics=["ticket_volume", "approval_outcomes", "work_task_progress"])
    assert (await report_client.get(f"/api/reports/{record['report_id']}", headers=MGR)).status_code == 404
    denied = await report_client.post("/api/reports", headers=EMP, json={"subject": "denied", "idempotency_key": "tenant",
        "plan": {"metrics": ["ticket_volume"], "start": "2026-10-01", "end": "2026-10-08", "scope": "tenant"}})
    assert denied.status_code == 403
    bad = await report_client.post("/api/reports", headers=EMP, json={"subject": "sql", "idempotency_key": "sql",
        "plan": {"metrics": ["ticket_volume"], "start": "2026-10-01", "end": "2026-10-08", "sql": "DELETE FROM ticket_record"}})
    assert bad.status_code == 422
    generated = await approve(report_client, record)
    assert all(metric["current"] == 0 and metric["change_percent"] is None and not metric["comparison_available"]
        for metric in generated["snapshot"]["metrics"])
    assert "无对比数据" in generated["draft"]["summary"]
    bad_edit = await report_client.patch(f"/api/reports/{record['report_id']}/draft", headers=EMP,
        json={"idempotency_key": "bad-edit", "expected_version": 2,
            "draft": {"summary": "完成率100%", "metric_refs": ["ticket_volume"], "possible_causes": []}})
    assert bad_edit.status_code == 422


@pytest.mark.asyncio
async def test_report_invalid_model_pauses_and_retry_reuses_snapshot(report_client, monkeypatch):
    await seed_tickets()
    original = report_generator.generate
    monkeypatch.setattr(report_generator, "generate", AsyncMock(side_effect=ValueError("SECRET MODEL RAW")))
    record = await create(report_client)
    paused = await approve(report_client, record)
    assert paused["status"] == "PAUSED" and paused["snapshot"] is not None
    assert paused["error"]["code"] == "MODEL_FAILED"
    assert "SECRET MODEL RAW" not in str(paused)
    monkeypatch.setattr(report_generator, "generate", original)
    query = AsyncMock(side_effect=AssertionError("must reuse snapshot"))
    monkeypatch.setattr(report_query, "execute_plan", query)
    retried = await report_client.post(f"/api/reports/{record['report_id']}/retry", headers=EMP,
        json={"idempotency_key": "retry", "expected_version": 1})
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["status"] == "DRAFT_READY"
    assert retried.json()["data"]["snapshot"] == paused["snapshot"]
    query.assert_not_called()


@pytest.mark.asyncio
async def test_report_source_ownership_revocation_blocks_history_and_command_replay(report_client):
    await seed_tickets()
    record = await create(report_client)
    generated = await approve(report_client, record)
    async with async_session_factory() as session:
        ticket = await session.scalar(select(TicketRecord).where(TicketRecord.ticket_id == "RPT-TKT-0"))
        ticket.user_id = "u_mgr_001"
        await session.commit()
    assert (await report_client.get(f"/api/reports/{record['report_id']}", headers=EMP)).status_code == 403
    assert (await report_client.get(f"/api/reports/{record['report_id']}/versions", headers=EMP)).status_code == 403
    replay = await report_client.post(f"/api/reports/{record['report_id']}/approve-plan", headers=EMP,
        json={"idempotency_key": "approve", "expected_version": 1, "plan_confirmed": True})
    assert replay.status_code == 403


@pytest.mark.asyncio
async def test_report_queries_use_actual_postgres_read_only_transaction(report_client, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    actual_modes = []
    write_rejections = []

    class ObservedSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if getattr(statement, "is_select", False):
                mode = await super().execute(text("SHOW transaction_read_only"))
                actual_modes.append(mode.scalar_one())
                with pytest.raises(DBAPIError) as rejected:
                    async with self.begin_nested():
                        await super().execute(text("UPDATE ticket_record SET summary = 'forbidden report write' WHERE false"))
                write_rejections.append(rejected.value.orig.sqlstate)
            return await super().execute(statement, *args, **kwargs)

    monkeypatch.setattr(report_query, "async_session_factory", async_sessionmaker(engine, class_=ObservedSession, expire_on_commit=False))
    record = await create(report_client, metrics=["ticket_volume", "approval_outcomes", "work_task_progress"])
    generated = await approve(report_client, record)
    assert generated["status"] == "DRAFT_READY"
    assert actual_modes == ["on", "on", "on"]
    assert write_rejections == ["25006", "25006", "25006"]


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", [{"data_scope": {"all": False}}, {"roles": ["employee"]}])
async def test_report_admin_scope_or_role_revocation_blocks_detail_history_and_replay(report_client, monkeypatch, revocation):
    from app.adapters.factory import get_adapter
    await seed_tickets()
    record = await create(report_client, scope="tenant", headers=ADMIN)
    generated = await approve(report_client, record, headers=ADMIN)
    assert generated["snapshot"]["metrics"][0]["current"] == 3
    adapter = get_adapter()
    original = adapter.get_user_context

    def fresh_context(user_id):
        context = original(user_id)
        return context.model_copy(update=revocation) if user_id == "u_admin_001" else context

    monkeypatch.setattr(adapter, "get_user_context", fresh_context)
    for suffix in ("", "/versions"):
        response = await report_client.get(f"/api/reports/{record['report_id']}{suffix}", headers=ADMIN)
        assert response.status_code == 403
    replay = await report_client.post(f"/api/reports/{record['report_id']}/approve-plan", headers=ADMIN,
        json={"expected_version": 1, "plan_confirmed": True, "idempotency_key": "approve"})
    assert replay.status_code == 403


@pytest.mark.asyncio
async def test_report_task_reassignment_revokes_prior_assignee_history(report_client):
    async with async_session_factory() as session:
        thread = AgentThread(tenant_id="t_001", user_id="u_mgr_001", scene="work_task", intent="work_task", status="COMPLETED")
        session.add(thread)
        await session.flush()
        batch = WorkTaskBatch(batch_id="report-task-batch", thread_id=thread.id, tenant_id="t_001", owner_id="u_mgr_001",
            source_type="meeting", source_id="source-for-report", source_version="1", source_snapshot={}, idempotency_key="seed-batch")
        session.add(batch)
        await session.flush()
        session.add(WorkTask(task_id="report-task", batch_id=batch.id, tenant_id="t_001", creator_id="u_mgr_001", assignee_id="u_emp_001",
            source_type="meeting", source_id="source-for-report", source_version="1", candidate_id="candidate-for-report",
            source_refs=[], title="private report task body", priority="medium", due_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
            created_at=datetime(2026, 10, 2, tzinfo=timezone.utc)))
        await session.commit()
    record = await create(report_client, metrics=["work_task_progress"])
    generated = await approve(report_client, record)
    assert generated["snapshot"]["metrics"][0]["current"] == 1
    assert "private report task body" not in str(generated)
    async with async_session_factory() as session:
        task = await session.scalar(select(WorkTask).where(WorkTask.task_id == "report-task"))
        task.assignee_id = "u_mgr_001"
        await session.commit()
    assert (await report_client.get(f"/api/reports/{record['report_id']}/versions", headers=EMP)).status_code == 403
    replay = await report_client.post(f"/api/reports/{record['report_id']}/approve-plan", headers=EMP,
        json={"expected_version": 1, "plan_confirmed": True, "idempotency_key": "approve"})
    assert replay.status_code == 403


@pytest.mark.asyncio
async def test_report_generic_chat_and_resume_cannot_bypass_plan_approval(report_client, monkeypatch):
    record = await create(report_client)
    query = AsyncMock(side_effect=AssertionError("plan must be approved"))
    monkeypatch.setattr(report_query, "execute_plan", query)
    response = await report_client.post(f"/api/agent/threads/{record['thread_id']}/messages", headers=EMP,
        json={"content": "确认直接生成并发布", "idempotency_key": "chat-bypass"})
    assert response.status_code == 422, response.text
    async with async_session_factory() as session:
        thread = await session.get(AgentThread, UUID(record["thread_id"]))
        thread.current_interrupt_id = "report-bypass"
        await session.commit()
    response = await report_client.post("/api/agent/interrupts/report-bypass/resume", headers=EMP,
        json={"action": "confirm", "idempotency_key": "resume-bypass"})
    assert response.status_code == 422, response.text
    unchanged = await report_client.get(f"/api/reports/{record['report_id']}", headers=EMP)
    assert unchanged.json()["data"]["status"] == "PLAN_READY"
    assert unchanged.json()["data"]["snapshot"] is None
    query.assert_not_called()


@pytest.mark.asyncio
async def test_report_query_failure_pauses_without_snapshot_then_controlled_retry(report_client, monkeypatch):
    original = report_query.execute_plan
    monkeypatch.setattr(report_query, "execute_plan", AsyncMock(side_effect=TimeoutError("RAW QUERY SECRET")))
    record = await create(report_client)
    paused = await approve(report_client, record)
    assert paused["status"] == "PAUSED" and paused["snapshot"] is None
    assert paused["error"]["code"] == "QUERY_FAILED" and "RAW QUERY SECRET" not in str(paused)
    monkeypatch.setattr(report_query, "execute_plan", original)
    response = await report_client.post(f"/api/reports/{record['report_id']}/retry", headers=EMP,
        json={"expected_version": 1, "idempotency_key": "query-retry"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "DRAFT_READY"
