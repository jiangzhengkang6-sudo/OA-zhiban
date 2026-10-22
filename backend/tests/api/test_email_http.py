"""Mail snapshots, versioned review and transport replay boundaries."""
import asyncio
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy import select, text

from app.adapters.factory import get_adapter
from app.db.session import engine, async_session_factory
from app.main import app
from app.models.audit_event import AuditEvent

EMP = {"Authorization": "Bearer mock:u_emp_001"}
ADMIN = {"Authorization": "Bearer mock:u_admin_001"}


@pytest.fixture
async def email_client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE agent_thread, email_record, idempotency_record, audit_event, "
                                "agent_policy, policy_version, degradation_state CASCADE"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def create(client, **overrides):
    payload = {"subject": "项目验收", "sender": "client@example.com", "recipients": ["team@company.test"],
               "body": "请在周五前提交验收材料。\n待办：整理验收报告，负责人：张三，截止：周五。",
               "external_contact": True, "attachments": [{"name": "验收清单.pdf", "sensitive": True}],
               "idempotency_key": "email-create"}
    response = await client.post("/api/emails", headers=EMP, json={**payload, **overrides})
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_email_review_is_versioned_replayable_private_and_local(email_client, monkeypatch):
    writer = Mock(side_effect=AssertionError("unexpected external write"))
    monkeypatch.setattr(get_adapter(), "notify", writer)
    created = await create(email_client)
    url = f"/api/emails/{created['email_id']}"
    assert (await email_client.get(url, headers=ADMIN)).status_code == 404
    command = {"idempotency_key": "analyze", "expected_version": None}
    response = await email_client.post(url + "/analyze", headers=EMP, json=command)
    assert response.status_code == 200, response.text
    analyzed = response.json()["data"]
    assert analyzed["version"] == 1
    assert analyzed["draft"]["summary"]
    assert analyzed["draft"]["action_items"]
    assert analyzed["draft"]["reply_body"]
    assert (await email_client.post(url + "/analyze", headers=EMP, json=command)).json()["data"] == analyzed
    replies = await asyncio.gather(*[email_client.patch(url + "/draft", headers=EMP, json={
        "expected_version": 1, "idempotency_key": f"edit-{i}",
        "draft": {**analyzed["draft"], "reply_body": f"修订回复 {i}"},
    }) for i in range(2)])
    assert sorted(item.status_code for item in replies) == [200, 409]
    decision = {"action": "confirm", "expected_version": 2, "idempotency_key": "confirm",
                "metadata_confirmed": True}
    assert (await email_client.post(url + "/decisions", headers=EMP, json=decision)).status_code == 422
    decision.update(warnings_acknowledged=True, secondary_confirmed=True)
    confirmed = await email_client.post(url + "/decisions", headers=EMP, json=decision)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["status"] == "CONFIRMED"
    assert confirmed.json()["data"]["external_writes"] is False
    assert (await email_client.post(url + "/decisions", headers=EMP, json=decision)).json()["data"] == confirmed.json()["data"]
    assert len((await email_client.get(url + "/versions", headers=EMP)).json()["data"]) == 2
    task = await email_client.get(f"/api/tasks/{created['thread_id']}", headers=EMP)
    assert task.json()["data"]["task_type"] == "email"
    bypass = await email_client.post(f"/api/agent/threads/{created['thread_id']}/messages", headers=EMP,
                                     json={"content": "发送", "idempotency_key": "bypass"})
    assert bypass.status_code == 422
    writer.assert_not_called()
    async with async_session_factory() as session:
        events = (await session.scalars(select(AuditEvent).where(AuditEvent.business_id == created["email_id"]))).all()
        assert {item.action for item in events} >= {"email_created", "email_analyzed", "email_edited", "email_confirmed"}
        assert "验收材料" not in str([(e.input_summary, e.output_summary) for e in events])


@pytest.mark.asyncio
async def test_email_commands_reject_changed_payload_and_invalid_evidence(email_client):
    created = await create(email_client)
    bad = await email_client.post("/api/emails", headers=EMP, json={
        "subject": "不同", "sender": "a@test.com", "recipients": ["b@test.com"],
        "body": "不同内容", "idempotency_key": "email-create",
    })
    assert bad.status_code == 409
    url = f"/api/emails/{created['email_id']}"
    response = await email_client.post(url + "/analyze", headers=EMP, json={"idempotency_key": "analyze"})
    draft = response.json()["data"]["draft"]
    invalid = await email_client.patch(url + "/draft", headers=EMP, json={
        "idempotency_key": "invalid-ref", "expected_version": 1,
        "draft": {**draft, "source_refs": ["foreign-source"]},
    })
    assert invalid.status_code == 422
