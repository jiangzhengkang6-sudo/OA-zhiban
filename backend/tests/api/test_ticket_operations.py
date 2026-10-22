"""B5 Task 5.1 authoritative ticket, duplicate and assignment contracts."""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text

from app.db.session import async_session_factory, engine
from app.main import app as fastapi_app
from app.models.agent_thread import AgentThread
from app.models.human_decision import HumanDecision
from app.models.handoff_snapshot import HandoffSnapshot
from app.models.human_queue_item import HumanQueueItem
from app.models.ticket_assignment_rule import TicketAssignmentRule
from app.models.ticket_feedback import TicketFeedback
from app.models.ticket_record import TicketRecord


@pytest.fixture
async def client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE ticket_feedback, ticket_record, ticket_assignment_rule, ticket_context, ticket_draft, "
            "human_queue_item, handoff_snapshot, human_decision, agent_message, agent_thread, policy_version, audit_event "
            "RESTART IDENTITY CASCADE"
        ))
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def emp_headers():
    return {"Authorization": "Bearer mock:u_emp_001"}


async def confirmed_thread(user_id="u_emp_001"):
    async with async_session_factory() as db:
        thread = AgentThread(user_id=user_id, tenant_id="t_001", scene="ticket", status="WAITING_HUMAN")
        db.add(thread)
        await db.flush()
        db.add(HumanDecision(thread_id=thread.id, actor_id=user_id, action="confirm", comment="确认"))
        await db.commit()
        return str(thread.id)


async def add_rule(category="IT", impact="个人", queue_id="q_it", version="r1"):
    async with async_session_factory() as db:
        db.add(TicketAssignmentRule(tenant_id="t_001", category=category, impact=impact,
                                    queue_id=queue_id, assignee_id="u_cs_001",
                                    rule_version=version, priority=10, enabled=True))
        await db.commit()


async def create(client, headers, thread_id, *, summary="电脑无法开机", idempotency_key=None, **extra):
    return await client.post("/api/tickets", headers=headers, json={
        "thread_id": thread_id, "idempotency_key": idempotency_key or thread_id,
        "category": "IT", "priority": "high", "summary": summary,
        "context": {"source": "b5-test"}, **extra,
    })


@pytest.mark.asyncio
async def test_create_persists_authoritative_record_and_applies_assignment_rule(client, emp_headers):
    await add_rule()
    thread_id = await confirmed_thread()
    response = await create(client, emp_headers, thread_id)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "open"
    assert data["queue_id"] == "q_it"
    assert data["assignment_rule_version"] == "r1"

    async with async_session_factory() as db:
        row = await db.scalar(select(TicketRecord).where(TicketRecord.ticket_id == data["ticket_id"]))
        assert row is not None
        assert row.queue_id == "q_it"
        assert row.assignee_id == "u_cs_001"


@pytest.mark.asyncio
async def test_duplicate_requires_explicit_merge_and_merge_is_idempotent(client, emp_headers):
    await add_rule()
    first = await create(client, emp_headers, await confirmed_thread())
    first_id = first.json()["data"]["ticket_id"]
    second_thread = await confirmed_thread()
    duplicate = await create(client, emp_headers, second_thread)
    assert duplicate.status_code == 200
    duplicate_data = duplicate.json()["data"]
    assert duplicate_data["status"] == "DUPLICATE_REVIEW"
    assert duplicate_data["duplicate_candidates"][0]["ticket_id"] == first_id

    merged = await create(client, emp_headers, second_thread, merge_ticket_id=first_id)
    assert merged.status_code == 200, merged.text
    assert merged.json()["data"]["ticket_id"] == first_id
    assert merged.json()["data"]["merged"] is True
    repeated = await create(client, emp_headers, second_thread, merge_ticket_id=first_id)
    assert repeated.status_code == 200
    assert repeated.json()["data"]["merged"] is True

    async with async_session_factory() as db:
        rows = (await db.scalars(select(TicketRecord))).all()
        assert len(rows) == 1
        assert str(second_thread) in (rows[0].merged_from or [])


@pytest.mark.asyncio
async def test_missing_assignment_rule_keeps_ticket_unassigned_without_fabricating_owner(client, emp_headers):
    thread_id = await confirmed_thread()
    response = await create(client, emp_headers, thread_id)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "open"
    assert data["queue_id"] is None
    assert data["assignment_error"]["code"] == "NO_ASSIGNMENT_RULE"


@pytest.mark.asyncio
async def test_ticket_query_is_tenant_and_owner_scoped(client, emp_headers):
    await add_rule()
    thread_id = await confirmed_thread()
    created = await create(client, emp_headers, thread_id)
    ticket_id = created.json()["data"]["ticket_id"]
    forbidden = await client.get("/api/tickets/" + ticket_id,
                                 headers={"Authorization": "Bearer mock:u_mgr_001"})
    assert forbidden.status_code == 403
    visible = await client.get("/api/tickets/" + ticket_id, headers=emp_headers)
    assert visible.status_code == 200
    assert visible.json()["data"]["ticket"]["ticket_id"] == ticket_id


@pytest.mark.asyncio
async def test_resolved_feedback_closes_ticket_and_is_idempotent(client, emp_headers):
    await add_rule()
    thread_id = await confirmed_thread()
    created = await create(client, emp_headers, thread_id)
    ticket_id = created.json()["data"]["ticket_id"]
    async with async_session_factory() as db:
        row = await db.scalar(select(TicketRecord).where(TicketRecord.ticket_id == ticket_id))
        row.status = "resolved"
        await db.commit()

    payload = {"resolved": True, "comment": "问题已解决", "idempotency_key": "feedback-001"}
    first = await client.post(f"/api/tickets/{ticket_id}/feedback", headers=emp_headers, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["ticket_status"] == "closed"
    repeated = await client.post(f"/api/tickets/{ticket_id}/feedback", headers=emp_headers, json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["data"]["feedback_id"] == first.json()["data"]["feedback_id"]

    changed = await client.post(
        f"/api/tickets/{ticket_id}/feedback", headers=emp_headers,
        json={**payload, "comment": "改写反馈"},
    )
    assert changed.status_code == 409

    async with async_session_factory() as db:
        feedbacks = (await db.scalars(select(TicketFeedback))).all()
        assert len(feedbacks) == 1


@pytest.mark.asyncio
async def test_negative_feedback_reopens_ticket_and_creates_review_item(client, emp_headers):
    await add_rule()
    thread_id = await confirmed_thread()
    created = await create(client, emp_headers, thread_id)
    ticket_id = created.json()["data"]["ticket_id"]
    async with async_session_factory() as db:
        row = await db.scalar(select(TicketRecord).where(TicketRecord.ticket_id == ticket_id))
        row.status = "resolved"
        await db.commit()

    payload = {"resolved": False, "comment": "仍然无法登录", "idempotency_key": "feedback-002"}
    response = await client.post(f"/api/tickets/{ticket_id}/feedback", headers=emp_headers, json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["ticket_status"] == "open"
    assert data["review_queue_item_id"]

    async with async_session_factory() as db:
        item = await db.get(HumanQueueItem, data["review_queue_item_id"])
        assert item.reason_code == "NEGATIVE_FEEDBACK"
        assert item.status == "OPEN"
        assert (await db.scalars(select(HumanQueueItem).where(
            HumanQueueItem.thread_id == thread_id,
            HumanQueueItem.reason_code == "NEGATIVE_FEEDBACK",
        ))).all().__len__() == 1


@pytest.mark.asyncio
async def test_feedback_is_owner_scoped(client, emp_headers):
    await add_rule()
    thread_id = await confirmed_thread()
    created = await create(client, emp_headers, thread_id)
    ticket_id = created.json()["data"]["ticket_id"]
    denied = await client.post(
        f"/api/tickets/{ticket_id}/feedback",
        headers={"Authorization": "Bearer mock:u_mgr_001"},
        json={"resolved": False, "comment": "越权", "idempotency_key": "feedback-003"},
    )
    assert denied.status_code == 403
