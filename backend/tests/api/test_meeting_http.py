"""Meeting requests exercise middleware, authorization and committed transactions."""

import asyncio
import json

import httpx
import pytest
from unittest.mock import Mock
from sqlalchemy import func, select, text

from app.adapters.factory import get_adapter
from app.db.session import async_session_factory, engine
from app.main import app
from app.models.agent_thread import AgentThread
from app.models.audit_event import AuditEvent
from app.models.meeting_decision import MeetingDecision
from app.models.meeting_draft_version import MeetingDraftVersion
from app.models.meeting_record import MeetingRecord
from app.models.agent_policy import AgentPolicy
from app.models.degradation_state import DegradationState


EMP = {"Authorization": "Bearer mock:u_emp_001"}
MGR = {"Authorization": "Bearer mock:u_mgr_001"}
CONTENT = "议题：验收安排。决定：采用灰度发布。待办：完成验收。"


@pytest.fixture
async def meeting_client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE agent_thread, meeting_record, idempotency_record, audit_event, "
            "runtime_span, agent_policy, policy_version, degradation_state RESTART IDENTITY CASCADE"
        ))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def create(client, *, key="create-1", headers=EMP, content=CONTENT):
    response = await client.post("/api/meetings", headers=headers, json={
        "title": "内部验收会", "content": content, "idempotency_key": key,
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def generate(client, meeting_id, *, key="generate-1"):
    response = await client.post(f"/api/meetings/{meeting_id}/generate", headers=EMP,
                                 json={"idempotency_key": key, "expected_version": None})
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_create_command_is_actor_scoped_and_replays_original_result(meeting_client):
    first = await create(meeting_client)
    other = await create(meeting_client, headers=MGR)
    assert other["meeting_id"] != first["meeting_id"]
    changed = await meeting_client.post("/api/meetings", headers=EMP, json={
        "title": "内部验收会", "content": "另一份会议原文", "idempotency_key": "create-1",
    })
    assert changed.status_code == 409
    await generate(meeting_client, first["meeting_id"])
    replay = await create(meeting_client)
    assert replay == first
    hidden = await meeting_client.get(f"/api/meetings/{first['meeting_id']}", headers=MGR)
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_http_versions_replay_and_regeneration_are_guarded(meeting_client):
    created = await create(meeting_client)
    mid = created["meeting_id"]
    generated = await generate(meeting_client, mid)
    assert generated["version"] == 1
    assert generated["draft"]["topics"]
    assert generated["draft"]["decisions"]
    assert generated["draft"]["action_items"]
    action = generated["draft"]["action_items"][0]
    assert action["assignee_candidate"] is None
    assert action["due_at_candidate"] is None
    assert action["needs_confirmation"] is True
    draft = {**generated["draft"], "summary": "人工补充摘要"}
    edit = {"draft": draft, "expected_version": 1, "idempotency_key": "edit-1"}
    edited = await meeting_client.patch(f"/api/meetings/{mid}/draft", headers=EMP, json=edit)
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["version"] == 2
    assert await generate(meeting_client, mid) == generated
    stale = await meeting_client.post(f"/api/meetings/{mid}/decisions", headers=EMP, json={
        "action": "confirm", "expected_version": 1, "idempotency_key": "stale-confirm",
    })
    assert stale.status_code == 409
    regen_payload = {"action": "regenerate", "expected_version": 2, "idempotency_key": "regen-1"}
    regen = await meeting_client.post(f"/api/meetings/{mid}/decisions", headers=EMP, json=regen_payload)
    assert regen.status_code == 200, regen.text
    assert regen.json()["data"]["version"] == 3
    replay_edit = await meeting_client.patch(f"/api/meetings/{mid}/draft", headers=EMP, json=edit)
    assert replay_edit.json()["data"] == edited.json()["data"]
    replay_regen = await meeting_client.post(f"/api/meetings/{mid}/decisions", headers=EMP, json=regen_payload)
    assert replay_regen.json()["data"] == regen.json()["data"]
    changed = await meeting_client.post(f"/api/meetings/{mid}/decisions", headers=EMP,
        json={**regen_payload, "expected_version": 3})
    assert changed.status_code == 409
    confirm = await meeting_client.post(f"/api/meetings/{mid}/decisions", headers=EMP, json={
        "action": "confirm", "expected_version": 3, "idempotency_key": "confirm-1",
    })
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["data"]["external_writes"] is False
    terminal_edit = await meeting_client.patch(f"/api/meetings/{mid}/draft", headers=EMP,
        json={**edit, "expected_version": 3, "idempotency_key": "edit-after-confirm"})
    assert terminal_edit.status_code == 422
    retry = await meeting_client.post(f"/api/meetings/{mid}/retry", headers=EMP,
        json={"idempotency_key": "retry-1", "expected_version": 3})
    assert retry.status_code == 422
    async with async_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(MeetingDraftVersion)) == 3
        assert await db.scalar(select(func.count()).select_from(MeetingDecision)) == 2


@pytest.mark.asyncio
async def test_confirmation_never_calls_external_oa_writers(meeting_client, monkeypatch):
    adapter = get_adapter()
    writers = {}
    for name in ("create_or_update_approval", "edit_leave_case", "create_or_merge_ticket", "notify", "update_leave_case"):
        writer = Mock(side_effect=AssertionError(f"unexpected external write: {name}"))
        monkeypatch.setattr(adapter, name, writer)
        writers[name] = writer

    created = await create(meeting_client)
    generated = await generate(meeting_client, created["meeting_id"])
    response = await meeting_client.post(f"/api/meetings/{created['meeting_id']}/decisions", headers=EMP, json={
        "action": "confirm", "expected_version": generated["version"], "idempotency_key": "confirm-zero-writes",
    })
    assert response.status_code == 200, response.text
    assert response.json()["data"]["external_writes"] is False
    for writer in writers.values():
        writer.assert_not_called()


@pytest.mark.asyncio
async def test_meeting_tasks_list_and_audit_are_linked_and_redacted(meeting_client):
    created = await create(meeting_client, content=CONTENT + "内部口令SECRET-98371。")
    mid = created["meeting_id"]
    assert created["thread_id"]
    listed = await meeting_client.get("/api/meetings", headers=EMP)
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1
    await generate(meeting_client, mid)
    task = await meeting_client.get(f"/api/tasks/{created['thread_id']}", headers=EMP)
    assert task.status_code == 200, task.text
    data = task.json()["data"]
    assert data["task_type"] == "meeting"
    assert data["business_id"] == mid
    assert data["business_status"] == "DRAFT_READY"
    assert set(data["available_actions"]) == {"edit", "confirm", "reject", "regenerate"}
    async with async_session_factory() as db:
        events = (await db.scalars(select(AuditEvent).where(AuditEvent.business_id == mid))).all()
        assert {event.action for event in events} >= {"meeting_created", "meeting_parsed", "meeting_generated"}
        assert all(event.thread_id and event.trace_id for event in events)
        summaries = json.dumps([(e.input_summary, e.output_summary) for e in events], ensure_ascii=False)
        assert "SECRET-98371" not in summaries
        assert "内部验收会" not in summaries
        thread = await db.get(AgentThread, created["thread_id"])
        assert thread.status == "WAITING_HUMAN"


@pytest.mark.asyncio
async def test_revocation_is_checked_for_reads_writes_and_replays(meeting_client, monkeypatch):
    created = await create(meeting_client)
    users = get_adapter()._state["users"]
    monkeypatch.setitem(users, "u_emp_001", {**users["u_emp_001"], "roles": []})
    read = await meeting_client.get(f"/api/meetings/{created['meeting_id']}", headers=EMP)
    listing = await meeting_client.get("/api/meetings", headers=EMP)
    replay = await meeting_client.post("/api/meetings", headers=EMP, json={
        "title": "内部验收会", "content": CONTENT, "idempotency_key": "create-1",
    })
    write = await meeting_client.post(f"/api/meetings/{created['meeting_id']}/generate", headers=EMP)
    assert [read.status_code, listing.status_code, replay.status_code, write.status_code] == [403] * 4


@pytest.mark.asyncio
async def test_cross_tenant_actor_cannot_read_or_write(meeting_client, monkeypatch):
    created = await create(meeting_client)
    users = get_adapter()._state["users"]
    monkeypatch.setitem(users, "u_mgr_001", {**users["u_mgr_001"], "tenant_id": "t_other"})
    read = await meeting_client.get(f"/api/meetings/{created['meeting_id']}", headers=MGR)
    write = await meeting_client.post(f"/api/meetings/{created['meeting_id']}/generate", headers=MGR)
    assert read.status_code == write.status_code
    assert read.status_code in {403, 404}


@pytest.mark.asyncio
async def test_concurrent_creation_and_edit_do_not_duplicate_versions(meeting_client):
    first, replay = await asyncio.gather(create(meeting_client), create(meeting_client))
    assert first == replay
    generated = await generate(meeting_client, first["meeting_id"])
    url = f"/api/meetings/{first['meeting_id']}/draft"
    responses = await asyncio.gather(*[
        meeting_client.patch(url, headers=EMP, json={
            "draft": {**generated["draft"], "summary": f"编辑 {i}"},
            "expected_version": 1, "idempotency_key": f"edit-{i}",
        }) for i in range(2)
    ])
    assert sorted(r.status_code for r in responses) == [200, 409]
    async with async_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(MeetingRecord)) == 1
        assert await db.scalar(select(func.count()).select_from(MeetingDraftVersion)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,code", [
    ({"title": "  ", "content": "有效会议"}, "10001"),
    ({"title": "会议", "content": "x" * 50001}, "10012"),
])
async def test_invalid_input_has_stable_errors(meeting_client, payload, code):
    response = await meeting_client.post("/api/meetings", headers=EMP, json=payload)
    assert response.status_code in {400, 422}
    if code == "10001":
        assert response.status_code == 422
        assert response.json()["detail"]
    else:
        assert response.json()["code"] == code
    async with async_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(MeetingRecord)) == 0


@pytest.mark.asyncio
async def test_generation_failure_resumes_postgres_checkpoint_after_restart(meeting_client, monkeypatch):
    from app.services import meeting_generator, meeting_service
    from app.graph.graph_service import runtime, extract_interrupt
    from app.models.runtime_span import RuntimeSpan

    original = meeting_generator.generate_meeting_draft
    attempts = []

    def flaky(segments):
        attempts.append([segment["segment_id"] for segment in segments])
        if len(attempts) == 1:
            raise TimeoutError("SECRET-MODEL-INPUT")
        return original(segments)

    monkeypatch.setattr(meeting_generator, "generate_meeting_draft", flaky)
    created = await create(meeting_client)
    mid = created["meeting_id"]
    paused = await generate(meeting_client, mid)
    assert paused["status"] == "PAUSED"
    assert paused["version"] is None
    assert paused["available_actions"] == ["retry"]
    assert await generate(meeting_client, mid) == paused
    await runtime.close()
    await runtime.initialize()
    snapshot = await runtime.get_state(created["thread_id"])
    assert snapshot.next
    retry = await meeting_client.post(f"/api/meetings/{mid}/retry", headers=EMP,
                                      json={"idempotency_key": "retry-1"})
    assert retry.status_code == 200, retry.text
    recovered = retry.json()["data"]
    assert recovered["status"] == "DRAFT_READY" and recovered["version"] == 1
    replay = await meeting_client.post(f"/api/meetings/{mid}/retry", headers=EMP,
                                       json={"idempotency_key": "retry-1"})
    assert replay.json()["data"] == recovered
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert extract_interrupt(await runtime.get_state(created["thread_id"]))
    async with async_session_factory() as db:
        events = (await db.scalars(select(AuditEvent).where(AuditEvent.business_id == mid))).all()
        names = [e.action for e in events]
        assert names.count("meeting_generated") == names.count("meeting_resumed") == names.count("meeting_paused") == 1
        assert "SECRET-MODEL-INPUT" not in json.dumps([(e.input_summary, e.output_summary) for e in events])
        assert await db.scalar(select(func.count()).select_from(MeetingDraftVersion)) == 1
        spans = (await db.scalars(select(RuntimeSpan).where(RuntimeSpan.thread_id == created["thread_id"]))).all()
        assert sorted(s.status for s in spans) == ["error", "success"]
        assert all(s.tool_name is None for s in spans)


@pytest.mark.asyncio
async def test_checkpoint_result_survives_business_transaction_rollback(meeting_client, monkeypatch):
    from app.services import meeting_service, meeting_generator
    from app.graph.graph_service import runtime

    created = await create(meeting_client)
    mid = created["meeting_id"]
    persist = meeting_service._persist_draft

    async def crash(*args, **kwargs):
        raise RuntimeError("simulate business commit failure")

    monkeypatch.setattr(meeting_service, "_persist_draft", crash)
    with pytest.raises(RuntimeError, match="business commit"):
        await generate(meeting_client, mid)
    monkeypatch.setattr(meeting_service, "_persist_draft", persist)
    await runtime.close()
    await runtime.initialize()

    def forbid(*args):
        raise AssertionError("已完成的生成不得再调用")

    monkeypatch.setattr(meeting_generator, "generate_meeting_draft", forbid)
    recovered = await generate(meeting_client, mid)
    assert recovered["status"] == "DRAFT_READY" and recovered["version"] == 1
    async with async_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(MeetingDraftVersion)) == 1
        assert await db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "meeting_generated")) == 1


@pytest.mark.asyncio
async def test_generic_thread_endpoints_cannot_bypass_meeting_review(meeting_client, monkeypatch):
    from app.graph.graph_service import runtime, extract_interrupt
    writes = []

    def forbidden_write(*args, **kwargs):
        writes.append(True)
        raise AssertionError("会议调用了外部写入")

    for name in ("create_or_update_approval", "create_or_merge_ticket", "notify"):
        monkeypatch.setattr(get_adapter(), name, forbidden_write)
    created = await create(meeting_client)
    mid, tid = created["meeting_id"], created["thread_id"]
    generated = await generate(meeting_client, mid)
    message = await meeting_client.post(f"/api/agent/threads/{tid}/messages", headers=EMP,
                                        json={"content": "确认", "idempotency_key": "bypass"})
    assert message.status_code == 422
    pending = extract_interrupt(await runtime.get_state(tid))
    assert pending
    bypass = await meeting_client.post(f"/api/agent/interrupts/{pending[0]}/resume", headers=EMP,
                                       json={"action": "confirm", "idempotency_key": "bypass-decision"})
    assert bypass.status_code == 422
    result = await meeting_client.post(f"/api/meetings/{mid}/decisions", headers=EMP,
        json={"action": "confirm", "expected_version": generated["version"], "idempotency_key": "confirm-final"})
    assert result.status_code == 200, result.text
    assert result.json()["data"]["status"] == "CONFIRMED"
    assert extract_interrupt(await runtime.get_state(tid)) is None
    assert writes == []


@pytest.mark.asyncio
async def test_meeting_thread_detail_rechecks_revoked_roles(meeting_client, monkeypatch):
    created = await create(meeting_client)
    users = get_adapter()._state["users"]
    monkeypatch.setitem(users, "u_emp_001", {**users["u_emp_001"], "roles": []})
    detail = await meeting_client.get(f"/api/agent/threads/{created['thread_id']}", headers=EMP)
    assert detail.status_code == 403


@pytest.mark.asyncio
async def test_retry_without_client_key_replays_after_success(meeting_client, monkeypatch):
    from app.services import meeting_generator
    original = meeting_generator.generate_meeting_draft

    def fail(segments):
        raise TimeoutError("unavailable")

    monkeypatch.setattr(meeting_generator, "generate_meeting_draft", fail)
    created = await create(meeting_client)
    paused = await generate(meeting_client, created["meeting_id"])
    assert paused["status"] == "PAUSED"
    monkeypatch.setattr(meeting_generator, "generate_meeting_draft", original)
    path = f"/api/meetings/{created['meeting_id']}/retry"
    first = await meeting_client.post(path, headers=EMP)
    assert first.status_code == 200, first.text
    repeated = await meeting_client.post(path, headers=EMP)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["data"] == first.json()["data"]
    task_retry = await meeting_client.post(f"/api/tasks/{created['thread_id']}/retry", headers=EMP)
    assert task_retry.status_code == 200, task_retry.text
    async with async_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(MeetingDraftVersion)) == 1


@pytest.mark.asyncio
async def test_generation_recovers_review_after_midflight_role_revocation(meeting_client, monkeypatch):
    from app.services import meeting_generator
    from app.graph.graph_service import runtime, extract_interrupt
    original = meeting_generator.generate_meeting_draft
    users = get_adapter()._state["users"]
    original_user = users["u_emp_001"]

    def revoke_after_generation(segments):
        result = original(segments)
        monkeypatch.setitem(users, "u_emp_001", {**original_user, "roles": []})
        return result

    created = await create(meeting_client)
    mid = created["meeting_id"]
    monkeypatch.setattr(meeting_generator, "generate_meeting_draft", revoke_after_generation)
    denied = await meeting_client.post(f"/api/meetings/{mid}/generate", headers=EMP,
                                      json={"idempotency_key": "midflight"})
    assert denied.status_code == 403
    monkeypatch.setitem(users, "u_emp_001", original_user)

    def forbid_generation(segments):
        raise AssertionError("completed draft regenerated")

    monkeypatch.setattr(meeting_generator, "generate_meeting_draft", forbid_generation)
    recovered = await generate(meeting_client, mid, key="midflight")
    assert recovered["status"] == "DRAFT_READY"
    assert extract_interrupt(await runtime.get_state(created["thread_id"]))
    confirmed = await meeting_client.post(f"/api/meetings/{mid}/decisions", headers=EMP,
        json={"action": "confirm", "expected_version": 1, "idempotency_key": "after-restoration"})
    assert confirmed.status_code == 200, confirmed.text


@pytest.mark.asyncio
async def test_blank_draft_is_rejected_without_business_changes(meeting_client):
    created = await create(meeting_client)
    generated = await generate(meeting_client, created["meeting_id"])
    response = await meeting_client.patch(f"/api/meetings/{created['meeting_id']}/draft", headers=EMP,
        json={"draft": {**generated["draft"], "summary": "   "}, "expected_version": 1,
              "idempotency_key": "blank-edit"})
    assert response.status_code == 422, response.text
    async with async_session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(MeetingDraftVersion)) == 1


@pytest.mark.asyncio
async def test_meeting_audit_queries_and_exports_are_tenant_scoped(meeting_client, monkeypatch):
    admin = {"Authorization": "Bearer mock:u_admin_001"}
    created = await create(meeting_client)
    mid = created["meeting_id"]
    own = await meeting_client.get("/api/audit/events", headers=admin, params={"business_id": mid})
    assert own.json()["data"]["total"] == 2
    own_export = await meeting_client.post("/api/audit/exports", headers=admin, json={"business_id": mid})
    assert own_export.json()["data"]["row_count"] == 2
    export_id = own_export.json()["data"]["id"]
    users = get_adapter()._state["users"]
    monkeypatch.setitem(users, "u_admin_001", {**users["u_admin_001"], "tenant_id": "other-tenant"})
    from app.adapters.mock_data import MOCK_USERS
    monkeypatch.setitem(MOCK_USERS, "u_admin_001", {**MOCK_USERS["u_admin_001"], "tenant_id": "other-tenant"})
    for params in ({"business_id": mid}, {}, {"trace_id": created["trace_id"]}):
        hidden = await meeting_client.get("/api/audit/events", headers=admin, params=params)
        assert hidden.status_code == 200
        events = hidden.json()["data"]
        assert all(item["business_id"] != mid for item in events["items"])
        if params:
            assert events["total"] == 0
    exported = await meeting_client.post("/api/audit/exports", headers=admin, json={"business_id": mid})
    assert exported.status_code == 200, exported.text
    assert exported.json()["data"]["row_count"] == 0
    for suffix in ("", "/download"):
        denied = await meeting_client.get(f"/api/audit/exports/{export_id}{suffix}", headers=admin)
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_failed_default_retry_replays_until_a_new_explicit_command(meeting_client, monkeypatch):
    from app.services import meeting_generator
    original = meeting_generator.generate_meeting_draft
    attempts = []

    def fail(segments):
        attempts.append(True)
        raise TimeoutError("unavailable")

    monkeypatch.setattr(meeting_generator, "generate_meeting_draft", fail)
    created = await create(meeting_client)
    mid = created["meeting_id"]
    await generate(meeting_client, mid)
    first = await meeting_client.post(f"/api/meetings/{mid}/retry", headers=EMP)
    assert first.json()["data"]["status"] == "PAUSED"
    repeated = await meeting_client.post(f"/api/meetings/{mid}/retry", headers=EMP)
    assert repeated.json()["data"] == first.json()["data"]
    assert len(attempts) == 2
    monkeypatch.setattr(meeting_generator, "generate_meeting_draft", original)
    recovered = await meeting_client.post(f"/api/meetings/{mid}/retry", headers=EMP,
                                         json={"idempotency_key": "new-retry-attempt"})
    assert recovered.json()["data"]["status"] == "DRAFT_READY"


@pytest.mark.asyncio
async def test_edit_after_decision_transaction_rollback_restores_review(meeting_client, monkeypatch):
    from app.services import meeting_service
    from app.graph.graph_service import runtime, extract_interrupt
    created = await create(meeting_client)
    mid = created["meeting_id"]
    generated = await generate(meeting_client, mid)
    original_finish = meeting_service._finish

    async def crash(session, record, command):
        if record.status == "CONFIRMED":
            raise RuntimeError("business transaction crash")
        return await original_finish(session, record, command)

    monkeypatch.setattr(meeting_service, "_finish", crash)
    with pytest.raises(RuntimeError, match="transaction crash"):
        await meeting_client.post(f"/api/meetings/{mid}/decisions", headers=EMP,
            json={"action": "confirm", "expected_version": 1, "idempotency_key": "crashed-confirm"})
    monkeypatch.setattr(meeting_service, "_finish", original_finish)
    edited = await meeting_client.patch(f"/api/meetings/{mid}/draft", headers=EMP,
        json={"draft": {**generated["draft"], "summary": "恢复后重新编辑"}, "expected_version": 1,
              "idempotency_key": "edit-after-crash"})
    assert edited.status_code == 200, edited.text
    assert extract_interrupt(await runtime.get_state(created["thread_id"]))
    confirmed = await meeting_client.post(f"/api/meetings/{mid}/decisions", headers=EMP,
        json={"action": "confirm", "expected_version": 2, "idempotency_key": "review-edited"})
    assert confirmed.status_code == 200, confirmed.text


@pytest.mark.asyncio
async def test_meeting_scene_switch_and_degradation_gate_generation(meeting_client):
    async with async_session_factory() as db:
        db.add(AgentPolicy(scene="meeting", scope_type="global", enabled=False, rule_version="v1"))
        await db.commit()
    blocked = await meeting_client.post("/api/meetings", headers=EMP,
        json={"title": "关停测试", "content": CONTENT, "idempotency_key": "switch-off"})
    assert blocked.status_code == 503
    async with async_session_factory() as db:
        policy = await db.scalar(select(AgentPolicy).where(AgentPolicy.scene == "meeting"))
        policy.enabled = True
        await db.commit()
    created = await create(meeting_client)
    generated = await generate(meeting_client, created["meeting_id"])
    async with async_session_factory() as db:
        policy = await db.scalar(select(AgentPolicy).where(AgentPolicy.scene == "meeting"))
        policy.enabled = False
        await db.commit()
    replay = await meeting_client.post(f"/api/meetings/{created['meeting_id']}/generate", headers=EMP,
        json={"idempotency_key": "generate-1", "expected_version": None})
    assert replay.status_code == 200
    assert replay.json()["data"] == generated
    create_replay = await meeting_client.post("/api/meetings", headers=EMP,
        json={"title": "内部验收会", "content": CONTENT, "idempotency_key": "create-1"})
    assert create_replay.status_code == 200
    assert create_replay.json()["data"] == created
    async with async_session_factory() as db:
        policy = await db.scalar(select(AgentPolicy).where(AgentPolicy.scene == "meeting"))
        policy.enabled = True
        await db.commit()
    async with async_session_factory() as db:
        db.add(DegradationState(scene="meeting", scope_type="tenant", scope_value="t_001",
                                enabled=True, new_task_action="fallback", inflight_action="pause",
                                reason="维护", created_by="u_admin_001"))
        await db.commit()
    rejected = await meeting_client.patch(f"/api/meetings/{created['meeting_id']}/draft", headers=EMP,
        json={"draft": generated["draft"], "expected_version": 1, "idempotency_key": "degraded-edit"})
    assert rejected.status_code == 503
    assert (await meeting_client.get(f"/api/meetings/{created['meeting_id']}", headers=EMP)).json()["data"]["status"] == "DRAFT_READY"
    new_task = await meeting_client.post("/api/meetings", headers=EMP,
        json={"title": "维护时创建", "content": CONTENT, "idempotency_key": "degraded-create"})
    assert new_task.status_code == 503
    async with async_session_factory() as db:
        state = await db.scalar(select(DegradationState).where(DegradationState.scene == "meeting"))
        state.enabled = False
        await db.commit()
    resumed = await meeting_client.patch(f"/api/meetings/{created['meeting_id']}/draft", headers=EMP,
        json={"draft": generated["draft"], "expected_version": 1, "idempotency_key": "degraded-edit"})
    assert resumed.status_code == 200
    assert resumed.json()["data"]["status"] == "REVIEWING"
