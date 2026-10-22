"""Actual HTTP task lifecycle, evidence, authority and scheduler isolation."""
from datetime import datetime, timezone, timedelta
import asyncio
from uuid import uuid4
from unittest.mock import patch
from unittest.mock import AsyncMock
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import func, select, text

from app.main import app
from app.db.session import engine, async_session_factory
from app.models.ticket_record import TicketRecord
from app.models.work_task import WorkTask
from app.models.work_task_event import WorkTaskEvent
from app.models.work_task_notification import WorkTaskNotification
from app.models.meeting_record import MeetingRecord
from app.models.meeting_draft_version import MeetingDraftVersion
from app.models.meeting_decision import MeetingDecision
from app.models.approval_instance import ApprovalInstance
from app.models.approval_node import ApprovalNode
from app.models.leave_application import LeaveApplication
from app.services.work_task_scheduler import scan_overdue

EMP = {"Authorization": "Bearer mock:u_emp_001"}
MGR = {"Authorization": "Bearer mock:u_mgr_001"}


@pytest.fixture
async def work_task_client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE agent_thread, ticket_record, meeting_record, approval_instance, leave_application, work_task_batch, idempotency_record, audit_event, "
            "runtime_span, model_usage, agent_policy, policy_version, degradation_state RESTART IDENTITY CASCADE"))
    async with async_session_factory() as session:
        session.add(TicketRecord(tenant_id="t_001", ticket_id="TASK-SOURCE-1", user_id="u_emp_001",
            category="it", priority="normal", impact="individual", summary="Repair the office printer",
            status="open", idempotency_key="seed", payload_hash="seed", assignee_id="u_mgr_001"))
        await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def batch(client, key="create"):
    response = await client.post("/api/work-tasks/batches", headers=EMP, json={"source_type": "ticket",
        "source_id": "TASK-SOURCE-1", "idempotency_key": key})
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    response = await client.post(f"/api/work-tasks/batches/{result['batch_id']}/extract", headers=EMP,
        json={"expected_version": 0, "idempotency_key": key + "-extract"})
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def prepared(client, *, assignee="u_emp_001", priority="normal", key="create", due=None):
    result = await batch(client, key)
    candidate = result["draft"]["candidates"][0]
    candidate.update(assignee_id=assignee, due_at=(due or datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), priority=priority)
    response = await client.patch(f"/api/work-tasks/batches/{result['batch_id']}/draft", headers=EMP,
        json={"expected_version": 1, "idempotency_key": key + "-save", "draft": {"candidates": [candidate]}})
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def confirmed(client, **kwargs):
    result = await prepared(client, **kwargs)
    decision = {"action": "confirm", "expected_version": 2, "metadata_confirmed": True,
        "risk_acknowledged": True, "selected_candidate_ids": [result["draft"]["candidates"][0]["candidate_id"]],
        "idempotency_key": "confirm"}
    response = await client.post(f"/api/work-tasks/batches/{result['batch_id']}/decisions", headers=EMP, json=decision)
    assert response.status_code == 200, response.text
    return response.json()["data"], decision


@pytest.mark.asyncio
async def test_task_is_independent_versioned_and_idempotent(work_task_client):
    client = work_task_client
    result, decision = await confirmed(client)
    assert result["status"] == "CONFIRMED" and result["external_writes"] is False
    task_id = result["task_ids"][0]
    replay = await client.post(f"/api/work-tasks/batches/{result['batch_id']}/decisions", headers=EMP, json=decision)
    assert replay.json()["data"] == result
    new_key = await client.post(f"/api/work-tasks/batches/{result['batch_id']}/decisions", headers=EMP,
        json={**decision, "idempotency_key": "other-key"})
    assert new_key.status_code == 422
    for action, version in [("start", 1), ("progress", 2), ("complete", 3), ("archive", 4)]:
        payload = {"action": action, "expected_version": version, "idempotency_key": action}
        if action == "progress":
            payload["progress"] = 70
        response = await client.post(f"/api/work-tasks/{task_id}/commands", headers=EMP, json=payload)
        assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "ARCHIVED"
    assert response.json()["data"]["available_actions"] == []
    forbidden = await client.post(f"/api/work-tasks/{task_id}/commands", headers=EMP,
        json={"action": "start", "expected_version": 5, "idempotency_key": "reopen"})
    assert forbidden.status_code == 422
    async with async_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkTask)) == 1
        assert await session.scalar(select(func.count()).select_from(WorkTaskEvent)) == 5


@pytest.mark.asyncio
async def test_risk_confirm_and_authoritative_assignee_are_required(work_task_client):
    result = await prepared(work_task_client, priority="high")
    payload = {"action": "confirm", "expected_version": 2, "metadata_confirmed": True,
        "selected_candidate_ids": [result["draft"]["candidates"][0]["candidate_id"]], "idempotency_key": "risk"}
    response = await work_task_client.post(f"/api/work-tasks/batches/{result['batch_id']}/decisions", headers=EMP, json=payload)
    assert response.status_code == 422
    response = await work_task_client.post(f"/api/work-tasks/batches/{result['batch_id']}/decisions", headers=EMP,
        json={**payload, "risk_acknowledged": True})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_foreign_source_and_invalid_evidence_are_rejected(work_task_client):
    foreign = await work_task_client.post("/api/work-tasks/batches", headers=MGR,
        json={"source_type": "approval", "source_id": "unknown", "idempotency_key": "foreign"})
    assert foreign.status_code in {403, 422}
    result = await batch(work_task_client)
    candidate = result["draft"]["candidates"][0]
    candidate["source_refs"] = ["fake-source"]
    invalid = await work_task_client.patch(f"/api/work-tasks/batches/{result['batch_id']}/draft", headers=EMP,
        json={"expected_version": 1, "idempotency_key": "bad-evidence", "draft": {"candidates": [candidate]}})
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_assignee_progress_and_stale_commands_are_guarded(work_task_client):
    result, _ = await confirmed(work_task_client, assignee="u_mgr_001")
    task_id = result["task_ids"][0]
    forbidden = await work_task_client.post(f"/api/work-tasks/{task_id}/commands", headers=EMP,
        json={"action": "start", "expected_version": 1, "idempotency_key": "wrong-actor"})
    assert forbidden.status_code == 403
    response = await work_task_client.post(f"/api/work-tasks/{task_id}/commands", headers=MGR,
        json={"action": "start", "expected_version": 1, "idempotency_key": "right-actor"})
    assert response.status_code == 200, response.text
    stale = await work_task_client.post(f"/api/work-tasks/{task_id}/commands", headers=MGR,
        json={"action": "complete", "expected_version": 1, "idempotency_key": "stale"})
    assert stale.status_code == 409
    async with async_session_factory() as session:
        source = await session.scalar(select(TicketRecord))
        source.assignee_id = None
        await session.commit()
    detail = await work_task_client.get(f"/api/work-tasks/{task_id}", headers=MGR)
    assert detail.status_code == 200
    assert detail.json()["data"]["source"] is None
    assert detail.json()["data"]["source_refs"] == []
    assert (await work_task_client.get(f"/api/work-tasks/batches/{result['batch_id']}", headers=MGR)).status_code == 404


@pytest.mark.asyncio
async def test_source_revocation_blocks_history_replays_and_new_commands(work_task_client):
    result, decision = await confirmed(work_task_client)
    async with async_session_factory() as session:
        source = await session.scalar(select(TicketRecord))
        source.user_id = "u_mgr_001"
        source.assignee_id = None
        await session.commit()
    for path in [f"/api/work-tasks/batches/{result['batch_id']}", f"/api/work-tasks/batches/{result['batch_id']}/versions"]:
        assert (await work_task_client.get(path, headers=EMP)).status_code == 403
    assert (await work_task_client.post(f"/api/work-tasks/batches/{result['batch_id']}/decisions", headers=EMP, json=decision)).status_code == 403
    assert (await work_task_client.post(f"/api/work-tasks/{result['task_ids'][0]}/commands", headers=EMP,
        json={"action": "start", "expected_version": 1, "idempotency_key": "revoked"})).status_code == 403


@pytest.mark.asyncio
async def test_candidate_cannot_be_duplicated_through_new_batch(work_task_client):
    await confirmed(work_task_client)
    result = await prepared(work_task_client, key="second")
    response = await work_task_client.post(f"/api/work-tasks/batches/{result['batch_id']}/decisions", headers=EMP,
        json={"action": "confirm", "expected_version": 2, "metadata_confirmed": True,
            "risk_acknowledged": True, "selected_candidate_ids": [result["draft"]["candidates"][0]["candidate_id"]],
            "idempotency_key": "second-confirm"})
    assert response.status_code == 409
    async with async_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkTask)) == 1


@pytest.mark.asyncio
async def test_overdue_stages_are_private_unique_and_terminal_safe(work_task_client):
    now = datetime.now(timezone.utc)
    result, _ = await confirmed(work_task_client, due=now - timedelta(hours=25))
    async with async_session_factory() as session:
        assert await scan_overdue(session, now) == 2
        await session.commit()
        assert await scan_overdue(session, now) == 0
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(WorkTaskNotification)) == 2
        task = await session.scalar(select(WorkTask))
        task.status = "COMPLETED"
        await session.commit()
        assert await scan_overdue(session, now + timedelta(days=1)) == 0
    notices = await work_task_client.get("/api/work-tasks/notifications", headers=EMP)
    assert notices.status_code == 200
    assert {n["stage"] for n in notices.json()["data"]} == {"overdue", "escalated"}
    assert (await work_task_client.get("/api/work-tasks/notifications", headers=MGR)).json()["data"] == []


@pytest.mark.asyncio
async def test_failed_extraction_pauses_then_retries(work_task_client):
    created = await work_task_client.post("/api/work-tasks/batches", headers=EMP,
        json={"source_type": "ticket", "source_id": "TASK-SOURCE-1", "idempotency_key": "failure"})
    batch_id = created.json()["data"]["batch_id"]
    with patch("app.services.work_task_generator.generate", side_effect=RuntimeError("PRIVATE SOURCE")):
        paused = await work_task_client.post(f"/api/work-tasks/batches/{batch_id}/extract", headers=EMP,
            json={"expected_version": 0, "idempotency_key": "failure-extract"})
    assert paused.json()["data"]["status"] == "PAUSED"
    assert "PRIVATE SOURCE" not in paused.text
    retried = await work_task_client.post(f"/api/work-tasks/batches/{batch_id}/extract", headers=EMP,
        json={"expected_version": 0, "idempotency_key": "retry"})
    assert retried.status_code == 200
    assert retried.json()["data"]["status"] == "DRAFT_READY"


@pytest.mark.asyncio
async def test_only_confirmed_meeting_version_can_supply_tasks(work_task_client):
    async with async_session_factory() as session:
        meeting = MeetingRecord(meeting_id="TASK-MEETING", tenant_id="t_001", owner_id="u_emp_001",
            title="Planning", current_version=2, idempotency_key="meeting-seed")
        session.add(meeting)
        await session.flush()
        first = MeetingDraftVersion(meeting_id=meeting.id, version=1, summary="Confirmed",
            action_items=[{"title": "Verify results", "priority": "high"}])
        session.add_all([first, MeetingDraftVersion(meeting_id=meeting.id, version=2, summary="Unconfirmed")])
        await session.flush()
        session.add(MeetingDecision(meeting_id=meeting.id, draft_version_id=first.id, actor_id="u_emp_001",
            action="confirm", idempotency_key="confirm-meeting", payload_hash="seed", trace_id="seed"))
        await session.commit()
    for version, status in [(2, 422), (1, 200)]:
        response = await work_task_client.post("/api/work-tasks/batches", headers=EMP,
            json={"source_type": "meeting", "source_id": "TASK-MEETING", "source_version": version,
                "idempotency_key": f"meeting-source-{version}"})
        assert response.status_code == status, response.text
    assert response.json()["data"]["source"]["version"] == "1"
    assert (await work_task_client.post("/api/work-tasks/batches", headers=MGR,
        json={"source_type": "meeting", "source_id": "TASK-MEETING", "source_version": 1,
            "idempotency_key": "foreign-meeting"})).status_code == 403


@pytest.mark.asyncio
async def test_completed_approval_is_visible_to_applicant_or_participating_approver(work_task_client):
    existing = await batch(work_task_client)
    from uuid import UUID
    async with async_session_factory() as session:
        approval = ApprovalInstance(thread_id=UUID(existing["thread_id"]), tenant_id="t_001",
            business_id="TASK-APPROVAL", version=1, route_version="r1", status="APPROVED")
        session.add_all([approval, LeaveApplication(thread_id=UUID(existing["thread_id"]), tenant_id="t_001",
            user_id="u_emp_001", business_id="TASK-APPROVAL", status="APPROVED")])
        await session.flush()
        session.add(ApprovalNode(instance_id=approval.id, node_order=1, approver_id="u_mgr_001",
            approver_name="Manager", status="APPROVED"))
        await session.commit()
    for user, status in [("u_emp_001", 200), ("u_mgr_001", 200), ("u_mgr_002", 403), ("u_admin_001", 403)]:
        response = await work_task_client.post("/api/work-tasks/batches", headers={"Authorization": f"Bearer mock:{user}"},
            json={"source_type": "approval", "source_id": "TASK-APPROVAL", "idempotency_key": "approval-" + user})
        assert response.status_code == status, response.text


@pytest.mark.asyncio
async def test_replayed_assignee_command_redacts_revoked_source(work_task_client):
    result, _ = await confirmed(work_task_client, assignee="u_mgr_001")
    task_id = result["task_ids"][0]
    command = {"action": "start", "expected_version": 1, "idempotency_key": "assignee-start"}
    response = await work_task_client.post(f"/api/work-tasks/{task_id}/commands", headers=MGR, json=command)
    assert response.status_code == 200 and response.json()["data"]["source"]
    async with async_session_factory() as session:
        source = await session.scalar(select(TicketRecord))
        source.assignee_id = None
        await session.commit()
    replay = await work_task_client.post(f"/api/work-tasks/{task_id}/commands", headers=MGR, json=command)
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["source"] is None
    assert replay.json()["data"]["source_refs"] == []
    progress = await work_task_client.post(f"/api/work-tasks/{task_id}/commands", headers=MGR,
        json={"action": "progress", "progress": 20, "expected_version": 2, "idempotency_key": "source-less-progress"})
    assert progress.status_code == 200


@pytest.mark.asyncio
async def test_reassignment_removes_former_assignee_and_resets_deadline_notifications(work_task_client):
    now = datetime.now(timezone.utc)
    result, _ = await confirmed(work_task_client, assignee="u_mgr_001", due=now - timedelta(hours=1))
    task_id = result["task_ids"][0]
    async with async_session_factory() as session:
        assert await scan_overdue(session, now) == 1
        await session.commit()
    response = await work_task_client.patch(f"/api/work-tasks/{task_id}", headers=EMP,
        json={"expected_version": 1, "idempotency_key": "reassign", "title": "Repair printer",
            "assignee_id": "u_emp_001", "due_at": (now - timedelta(minutes=30)).isoformat(),
            "priority": "normal", "sensitive": False, "metadata_confirmed": True, "risk_acknowledged": True})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["deadline_version"] == 2
    assert (await work_task_client.get(f"/api/work-tasks/{task_id}", headers=MGR)).status_code == 404
    async with async_session_factory() as session:
        assert await scan_overdue(session, now) == 1
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(WorkTaskNotification)) == 2
    assert (await work_task_client.get("/api/work-tasks/notifications", headers=MGR)).json()["data"] == []


@pytest.mark.asyncio
async def test_concurrent_duplicate_confirmation_creates_one_task(work_task_client):
    results = [await prepared(work_task_client, key=key) for key in ("race-a", "race-b")]
    responses = await asyncio.gather(*(work_task_client.post(f"/api/work-tasks/batches/{result['batch_id']}/decisions",
        headers=EMP, json={"action": "confirm", "expected_version": 2, "metadata_confirmed": True,
            "selected_candidate_ids": [result["draft"]["candidates"][0]["candidate_id"]],
            "idempotency_key": result["batch_id"]}) for result in results))
    assert sorted(response.status_code for response in responses) == [200, 409]
    async with async_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkTask)) == 1
        assert await session.scalar(select(func.count()).select_from(WorkTaskEvent)) == 1


@pytest.mark.asyncio
async def test_reminder_sweep_reaches_tasks_after_first_two_hundred(work_task_client):
    now = datetime.now(timezone.utc)
    await confirmed(work_task_client, due=now - timedelta(hours=1))
    async with async_session_factory() as session:
        first = await session.scalar(select(WorkTask))
        fields = {column.name: getattr(first, column.name) for column in WorkTask.__table__.columns
            if column.name not in {"id", "task_id", "candidate_id", "created_at", "updated_at"}}
        session.add_all([WorkTask(id=uuid4(), task_id=f"WT-SCAN-{index}", candidate_id=f"scan-{index}", **fields)
            for index in range(210)])
        await session.commit()
        assert await scan_overdue(session, now) == 200
        await session.commit()
        assert await scan_overdue(session, now) == 11
        await session.commit()
        assert await scan_overdue(session, now) == 0
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(WorkTaskNotification)) == 211


@pytest.mark.asyncio
async def test_unavailable_recipients_rotate_out_of_the_reminder_scan_window(work_task_client):
    now = datetime.now(timezone.utc)
    await confirmed(work_task_client, due=now - timedelta(minutes=30))
    async with async_session_factory() as session:
        valid = await session.scalar(select(WorkTask))
        fields = {column.name: getattr(valid, column.name) for column in WorkTask.__table__.columns
            if column.name not in {"id", "task_id", "candidate_id", "assignee_id", "due_at", "created_at", "updated_at"}}
        session.add_all([WorkTask(id=uuid4(), task_id=f"WT-BLOCKED-{index}", candidate_id=f"blocked-{index}",
            assignee_id="removed-user", due_at=now - timedelta(hours=1), **fields) for index in range(2000)])
        await session.commit()
        for offset in range(10):
            assert await scan_overdue(session, now + timedelta(seconds=offset)) == 0
            await session.commit()
        assert await scan_overdue(session, now + timedelta(seconds=10)) == 1
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(WorkTaskNotification)) == 1
        await session.refresh(valid)
        assert valid.version == 1


@pytest.mark.asyncio
async def test_scene_disable_prevents_extraction_and_reminders(work_task_client):
    now = datetime.now(timezone.utc)
    await confirmed(work_task_client, due=now - timedelta(hours=1))
    with patch("app.services.policy_service.is_scene_enabled", return_value=False):
        response = await work_task_client.post("/api/work-tasks/batches", headers=EMP,
            json={"source_type": "ticket", "source_id": "TASK-SOURCE-1", "idempotency_key": "disabled"})
        assert response.status_code == 503
        async with async_session_factory() as session:
            assert await scan_overdue(session, now) == 0


@pytest.mark.asyncio
async def test_notification_read_replays_after_task_version_changes(work_task_client):
    now = datetime.now(timezone.utc)
    result, _ = await confirmed(work_task_client, due=now - timedelta(hours=1))
    async with async_session_factory() as session:
        await scan_overdue(session, now)
        await session.commit()
    notices = (await work_task_client.get("/api/work-tasks/notifications", headers=EMP)).json()["data"]
    payload = {"expected_version": 1, "idempotency_key": "read-notice"}
    path = f"/api/work-tasks/notifications/{notices[0]['id']}/read"
    assert (await work_task_client.post(path, headers=EMP, json=payload)).status_code == 200
    assert (await work_task_client.post(f"/api/work-tasks/{result['task_ids'][0]}/commands", headers=EMP,
        json={"action": "start", "expected_version": 1, "idempotency_key": "start-after-read"})).status_code == 200
    assert (await work_task_client.post(path, headers=EMP, json=payload)).status_code == 200


@pytest.mark.asyncio
async def test_invalid_assignee_cannot_become_a_business_task(work_task_client):
    result = await prepared(work_task_client, assignee="not-a-real-user")
    response = await work_task_client.post(f"/api/work-tasks/batches/{result['batch_id']}/decisions", headers=EMP,
        json={"action": "confirm", "expected_version": 2, "metadata_confirmed": True,
            "selected_candidate_ids": [result["draft"]["candidates"][0]["candidate_id"]], "idempotency_key": "bad-assignee"})
    assert response.status_code == 422
    async with async_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkTask)) == 0


@pytest.mark.asyncio
async def test_source_revocation_during_generation_leaves_no_draft(work_task_client):
    response = await work_task_client.post("/api/work-tasks/batches", headers=EMP,
        json={"source_type": "ticket", "source_id": "TASK-SOURCE-1", "idempotency_key": "during-create"})
    batch_id = response.json()["data"]["batch_id"]
    async def generate_and_revoke(source, usage=None):
        from app.services.work_task_generator import extract_candidates
        async with async_session_factory() as session:
            row = await session.scalar(select(TicketRecord))
            row.user_id = "u_mgr_001"
            row.assignee_id = None
            await session.commit()
        return extract_candidates(source)
    with patch("app.services.work_task_generator.generate", side_effect=generate_and_revoke):
        response = await work_task_client.post(f"/api/work-tasks/batches/{batch_id}/extract", headers=EMP,
            json={"expected_version": 0, "idempotency_key": "during-extract"})
    assert response.status_code == 403
    from app.models.work_task_draft_version import WorkTaskDraftVersion
    from app.models.work_task_batch import WorkTaskBatch
    async with async_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkTaskDraftVersion)) == 0
        stored = await session.scalar(select(WorkTaskBatch))
        assert stored.status == "CREATED" and stored.current_version == 0


@pytest.mark.asyncio
async def test_failed_audit_rolls_back_tasks_events_and_confirmed_state(work_task_client):
    from app.core.errors import AppException
    from app.core.enums import ErrorCode
    result = await prepared(work_task_client)
    with patch("app.services.work_task_service.audit_service.audit",
        side_effect=AppException(ErrorCode.DEPENDENCY_FAILED, "Audit unavailable", http_status=503)):
        response = await work_task_client.post(f"/api/work-tasks/batches/{result['batch_id']}/decisions", headers=EMP,
            json={"action": "confirm", "expected_version": 2, "metadata_confirmed": True,
                "selected_candidate_ids": [result["draft"]["candidates"][0]["candidate_id"]], "idempotency_key": "audit-fail"})
    assert response.status_code == 503
    async with async_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkTask)) == 0
        assert await session.scalar(select(func.count()).select_from(WorkTaskEvent)) == 0
    response = await work_task_client.get(f"/api/work-tasks/batches/{result['batch_id']}", headers=EMP)
    assert response.json()["data"]["status"] == "DRAFT_READY"


@pytest.mark.asyncio
async def test_extraction_usage_is_known_or_explicitly_missing(work_task_client, monkeypatch):
    from app.models.model_usage import ModelUsage
    from app.schemas.work_task import WorkTaskDraftDTO
    from app.core.config import get_settings
    from app.services.work_task_generator import LLMFactory
    await batch(work_task_client, key="missing-usage")
    async with async_session_factory() as session:
        missing = await session.scalar(select(ModelUsage).order_by(ModelUsage.created_at.desc()).limit(1))
        assert missing.usage_missing is True and missing.total_tokens is None
    created = await work_task_client.post("/api/work-tasks/batches", headers=EMP,
        json={"source_type": "ticket", "source_id": "TASK-SOURCE-1", "idempotency_key": "known-usage"})
    record = created.json()["data"]
    llm = SimpleNamespace(last_usage={"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30},
        structured=AsyncMock(return_value=WorkTaskDraftDTO(candidates=[{"candidate_id": "llm-guessed",
            "title": "Repair printer", "source_refs": [record["source"]["ref"]]}])))
    monkeypatch.setattr(get_settings(), "llm_provider", "ark")
    monkeypatch.setattr(LLMFactory, "get_llm", lambda: llm)
    response = await work_task_client.post(f"/api/work-tasks/batches/{record['batch_id']}/extract", headers=EMP,
        json={"expected_version": 0, "idempotency_key": "known-extract"})
    assert response.status_code == 200, response.text
    assert llm.structured.await_args.kwargs["max_tokens"] == 2048
    async with async_session_factory() as session:
        known = await session.scalar(select(ModelUsage).order_by(ModelUsage.created_at.desc()).limit(1))
        assert known.provider == "ark" and known.usage_missing is False
        assert (known.input_tokens, known.output_tokens, known.total_tokens) == (21, 9, 30)
