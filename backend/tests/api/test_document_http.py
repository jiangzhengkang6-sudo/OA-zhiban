"""Document drafting lifecycle, replay and access-boundary tests."""

import asyncio
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy import func, select, text

from app.adapters.factory import get_adapter
from app.db.session import async_session_factory, engine
from app.main import app
from app.models.agent_thread import AgentThread
from app.models.audit_event import AuditEvent


EMP = {"Authorization": "Bearer mock:u_emp_001"}
MGR = {"Authorization": "Bearer mock:u_mgr_001"}


@pytest.fixture
async def document_client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE agent_thread, document_record, idempotency_record, audit_event, "
            "runtime_span, agent_policy, policy_version, degradation_state RESTART IDENTITY CASCADE"
        ))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def create_document(client, *, key="doc-create-1", headers=EMP):
    response = await client.post("/api/documents", headers=headers, json={
        "template_id": "notice",
        "subject": "项目验收通知",
        "recipient": "项目组",
        "deadline": "本周五",
        "basis": "依据项目计划",
        "key_points": "完成材料提交和现场验收",
        "classification": "internal",
        "distribution": "项目组内部",
        "use_knowledge": False,
        "idempotency_key": key,
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def generate_document(client, document_id, *, key="doc-generate-1"):
    response = await client.post(f"/api/documents/{document_id}/generate", headers=EMP, json={
        "idempotency_key": key, "expected_version": None,
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_document_lifecycle_is_versioned_replayable_and_terminal(document_client):
    templates = await document_client.get("/api/documents/templates", headers=EMP)
    assert templates.status_code == 200
    assert {item["id"] for item in templates.json()["data"]} == {"official", "notice", "report", "summary"}

    created = await create_document(document_client)
    assert created["status"] == "CREATED"
    generated = await generate_document(document_client, created["document_id"])
    assert generated["status"] == "DRAFT_READY"
    assert generated["version"] == 1
    assert generated["draft"]["source_refs"]
    assert not [item for item in generated["checks"] if item["severity"] == "error"]

    replay = await generate_document(document_client, created["document_id"])
    assert replay == generated
    body = generated["draft"]["body"].replace("完成材料提交和现场验收", "完成材料提交、现场验收和复盘")
    edit_payload = {
        "idempotency_key": "doc-edit-1", "expected_version": 1,
        "draft": {"body": body, "source_refs": generated["draft"]["source_refs"]},
    }
    edited = await document_client.patch(f"/api/documents/{created['document_id']}/draft", headers=EMP, json=edit_payload)
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["version"] == 2

    stale = await document_client.post(f"/api/documents/{created['document_id']}/decisions", headers=EMP, json={
        "action": "confirm", "expected_version": 1, "idempotency_key": "stale",
        "metadata_confirmed": True, "warnings_acknowledged": True,
    })
    assert stale.status_code == 409
    confirmed = await document_client.post(f"/api/documents/{created['document_id']}/decisions", headers=EMP, json={
        "action": "confirm", "expected_version": 2, "idempotency_key": "confirm-1",
        "metadata_confirmed": True, "warnings_acknowledged": True,
    })
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "CONFIRMED"
    assert confirmed.json()["data"]["external_writes"] is False
    terminal = await document_client.patch(f"/api/documents/{created['document_id']}/draft", headers=EMP, json={
        **edit_payload, "idempotency_key": "terminal-edit", "expected_version": 2,
    })
    assert terminal.status_code == 422
    versions = await document_client.get(f"/api/documents/{created['document_id']}/versions", headers=EMP)
    assert [item["version"] for item in versions.json()["data"]] == [1, 2]


@pytest.mark.asyncio
async def test_document_owner_scope_concurrency_tasks_and_redacted_audit(document_client):
    created = await create_document(document_client)
    hidden = await document_client.get(f"/api/documents/{created['document_id']}", headers=MGR)
    assert hidden.status_code == 404
    generated = await generate_document(document_client, created["document_id"])
    url = f"/api/documents/{created['document_id']}/draft"
    responses = await asyncio.gather(*[document_client.patch(url, headers=EMP, json={
        "idempotency_key": f"parallel-{index}", "expected_version": 1,
        "draft": {"body": generated["draft"]["body"] + f"\n修订 {index}",
                  "source_refs": generated["draft"]["source_refs"]},
    }) for index in range(2)])
    assert sorted(item.status_code for item in responses) == [200, 409]
    task = await document_client.get(f"/api/tasks/{created['thread_id']}", headers=EMP)
    assert task.status_code == 200
    assert task.json()["data"]["task_type"] == "document"
    message = await document_client.post(f"/api/agent/threads/{created['thread_id']}/messages", headers=EMP, json={
        "content": "确认", "idempotency_key": "document-bypass",
    })
    assert message.status_code == 422
    async with async_session_factory() as session:
        events = (await session.scalars(select(AuditEvent).where(AuditEvent.business_id == created["document_id"]))).all()
        assert {item.action for item in events} >= {"document_created", "document_generated", "document_edited"}
        assert "完成材料提交和现场验收" not in str([(item.input_summary, item.output_summary) for item in events])


@pytest.mark.asyncio
async def test_document_confirmation_has_no_external_writes(document_client, monkeypatch):
    adapter = get_adapter()
    writers = []
    for name in ("create_or_update_approval", "edit_leave_case", "create_or_merge_ticket", "notify", "update_leave_case"):
        writer = Mock(side_effect=AssertionError(f"unexpected external write: {name}"))
        monkeypatch.setattr(adapter, name, writer)
        writers.append(writer)
    created = await create_document(document_client)
    generated = await generate_document(document_client, created["document_id"])
    response = await document_client.post(f"/api/documents/{created['document_id']}/decisions", headers=EMP, json={
        "action": "confirm", "expected_version": generated["version"],
        "idempotency_key": "confirm-zero-write", "metadata_confirmed": True,
        "warnings_acknowledged": True,
    })
    assert response.status_code == 200, response.text
    for writer in writers:
        writer.assert_not_called()
