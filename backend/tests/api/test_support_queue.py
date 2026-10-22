"""B5 Task 5.2 human support queue operation contracts."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text

from app.db.session import async_session_factory, engine
from app.main import app as fastapi_app
from app.models.handoff_snapshot import HandoffSnapshot
from app.models.human_queue_item import HumanQueueItem
from app.models.ticket_record import TicketRecord


@pytest.fixture
async def client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE ticket_record, human_queue_item, handoff_snapshot, "
            "agent_thread, audit_event RESTART IDENTITY CASCADE"
        ))
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def cs_headers():
    return {"Authorization": "Bearer mock:u_cs_001"}


@pytest.fixture
def cs2_headers():
    return {"Authorization": "Bearer mock:u_cs_002"}


@pytest.fixture
def emp_headers():
    return {"Authorization": "Bearer mock:u_emp_001"}


async def seed_item(*, tenant_id="t_001", user_id="u_emp_001", with_ticket=True):
    thread_id = uuid4()
    async with async_session_factory() as db:
        item = HumanQueueItem(
            tenant_id=tenant_id,
            thread_id=thread_id,
            user_id=user_id,
            scene="ticket",
            reason_code="FAQ_NO_EVIDENCE",
            status="OPEN",
            context_summary="用户无法登录",
        )
        db.add(item)
        await db.flush()
        db.add(HandoffSnapshot(
            queue_item_id=item.id,
            tenant_id=tenant_id,
            thread_id=thread_id,
            payload={"summary": "用户无法登录", "scene": "ticket"},
            payload_hash="hash",
        ))
        ticket_id = None
        if with_ticket:
            ticket_id = f"TK-{uuid4().hex[:10].upper()}"
            db.add(TicketRecord(
                tenant_id=tenant_id,
                ticket_id=ticket_id,
                thread_id=thread_id,
                user_id=user_id,
                category="IT",
                priority="high",
                impact="个人",
                summary="用户无法登录",
                status="open",
                queue_id="q_it",
                assignee_id=None,
                assignment_rule_version=None,
                assignment_error=None,
                merged_from=[],
                context={"source": "support-test"},
                idempotency_key=str(thread_id),
                payload_hash="hash",
            ))
        await db.commit()
        return str(item.id), thread_id, ticket_id


@pytest.mark.asyncio
async def test_queue_list_is_tenant_scoped_and_non_cs_is_rejected(client, cs_headers, emp_headers):
    item_id, _, _ = await seed_item()
    await seed_item(tenant_id="t_other", user_id="u_other", with_ticket=False)

    response = await client.get("/api/support/queue", headers=cs_headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["queue_item_id"] == item_id

    denied = await client.get("/api/support/queue", headers=emp_headers)
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_queue_item_snapshot_direct_link_is_role_and_tenant_scoped(client, cs_headers, emp_headers):
    item_id, _, _ = await seed_item()
    other_id, _, _ = await seed_item(tenant_id="t_other", user_id="u_other", with_ticket=False)
    response = await client.get(f"/api/support/queue/{item_id}", headers=cs_headers)
    assert response.status_code == 200
    assert response.json()["data"]["snapshot"]["summary"] == "用户无法登录"
    assert (await client.get(f"/api/support/queue/{item_id}", headers=emp_headers)).status_code == 403
    assert (await client.get(f"/api/support/queue/{other_id}", headers=cs_headers)).status_code == 404


@pytest.mark.asyncio
async def test_concurrent_accept_only_one_request_wins(client, cs_headers):
    item_id, _, _ = await seed_item()

    async def accept():
        return await client.post(f"/api/support/queue/{item_id}/accept", headers=cs_headers)

    first, second = await asyncio.gather(accept(), accept())
    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 409]
    winner = first if first.status_code == 200 else second
    assert winner.json()["data"]["status"] == "IN_PROGRESS"
    assert winner.json()["data"]["assignee_id"] == "u_cs_001"


@pytest.mark.asyncio
async def test_transfer_and_complete_write_back_to_ticket(client, cs_headers, cs2_headers):
    item_id, _, ticket_id = await seed_item()
    accepted = await client.post(f"/api/support/queue/{item_id}/accept", headers=cs_headers)
    assert accepted.status_code == 200, accepted.text

    transferred = await client.post(
        f"/api/support/queue/{item_id}/assign",
        headers=cs_headers,
        json={"assignee_id": "u_cs_002"},
    )
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["data"]["assignee_id"] == "u_cs_002"

    completed = await client.post(
        f"/api/support/queue/{item_id}/complete",
        headers=cs2_headers,
        json={"resolution": "已重置账号并恢复登录", "status": "resolved"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["status"] == "RESOLVED"
    assert completed.json()["data"]["ticket_id"] == ticket_id

    async with async_session_factory() as db:
        item = await db.get(HumanQueueItem, item_id)
        ticket = await db.scalar(select(TicketRecord).where(TicketRecord.ticket_id == ticket_id))
        assert item.status == "RESOLVED"
        assert ticket.status == "resolved"
        assert ticket.context["resolution"] == "已重置账号并恢复登录"


@pytest.mark.asyncio
async def test_accepting_missing_item_returns_not_found(client, cs_headers):
    response = await client.post(f"/api/support/queue/{uuid4()}/accept", headers=cs_headers)
    assert response.status_code == 404
