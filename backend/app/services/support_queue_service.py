"""Transactional operations for the human support queue."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.context import CurrentUser
from ..core.errors import AppException, ErrorCode, conflict, not_found
from ..models.handoff_snapshot import HandoffSnapshot
from ..models.human_queue_item import HumanQueueItem
from ..models.ticket_record import TicketRecord


def _sla_status(status: str) -> str:
    return {
        "OPEN": "pending",
        "IN_PROGRESS": "within_sla",
        "RESOLVED": "met",
        "CLOSED": "met",
    }.get(status, "unknown")


async def _load_item(session: AsyncSession, actor: CurrentUser, item_id: UUID | str,
                     *, for_update: bool = False) -> HumanQueueItem:
    statement = select(HumanQueueItem).where(
        HumanQueueItem.id == item_id,
        HumanQueueItem.tenant_id == actor.tenant_id,
    )
    if for_update:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise not_found("人工队列项不存在")
    return item


async def _snapshot(session: AsyncSession, item_id: UUID) -> dict:
    row = await session.scalar(select(HandoffSnapshot).where(
        HandoffSnapshot.queue_item_id == item_id,
    ).order_by(HandoffSnapshot.created_at.desc()).limit(1))
    return deepcopy(row.payload) if row else {}


async def _linked_ticket(session: AsyncSession, item: HumanQueueItem) -> TicketRecord | None:
    return await session.scalar(select(TicketRecord).where(
        TicketRecord.tenant_id == item.tenant_id,
        TicketRecord.thread_id == item.thread_id,
    ).order_by(TicketRecord.updated_at.desc()).limit(1))


async def _project(session: AsyncSession, item: HumanQueueItem) -> dict:
    ticket = await _linked_ticket(session, item)
    return {
        "queue_item_id": str(item.id),
        "tenant_id": item.tenant_id,
        "thread_id": str(item.thread_id),
        "user_id": item.user_id,
        "scene": item.scene,
        "reason_code": item.reason_code,
        "status": item.status,
        "assignee_id": item.assignee_id,
        "context_summary": item.context_summary,
        "snapshot": await _snapshot(session, item.id),
        "ticket_id": ticket.ticket_id if ticket else None,
        "ticket_status": ticket.status if ticket else None,
        "sla_status": _sla_status(item.status),
    }


async def list_queue(session: AsyncSession, actor: CurrentUser, *, status: str | None = None,
                     page: int = 1, page_size: int = 20) -> dict:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    filters = [HumanQueueItem.tenant_id == actor.tenant_id]
    if status:
        filters.append(HumanQueueItem.status == status.upper())
    total = await session.scalar(select(func.count(HumanQueueItem.id)).where(*filters))
    rows = (await session.scalars(
        select(HumanQueueItem).where(*filters)
        .order_by(HumanQueueItem.created_at.asc())
        .offset((page - 1) * page_size).limit(page_size)
    )).all()
    return {
        "items": [await _project(session, row) for row in rows],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


async def get_item(session: AsyncSession, actor: CurrentUser, item_id: UUID | str) -> dict:
    return await _project(session, await _load_item(session, actor, item_id))


async def accept(session: AsyncSession, actor: CurrentUser, item_id: UUID | str) -> dict:
    item = await _load_item(session, actor, item_id, for_update=True)
    if item.status == "IN_PROGRESS":
        raise conflict("人工队列项已被受理", ErrorCode.IDEMPOTENCY_CONFLICT)
    if item.status != "OPEN":
        raise AppException(ErrorCode.INVALID_STATE, "人工队列项当前不可受理", http_status=422)
    item.status = "IN_PROGRESS"
    item.assignee_id = actor.user_id
    await session.flush()
    return await _project(session, item)


async def assign(session: AsyncSession, actor: CurrentUser, item_id: UUID | str,
                 assignee_id: str) -> dict:
    item = await _load_item(session, actor, item_id, for_update=True)
    if item.status not in {"OPEN", "IN_PROGRESS"}:
        raise AppException(ErrorCode.INVALID_STATE, "人工队列项当前不可转派", http_status=422)
    item.assignee_id = assignee_id
    await session.flush()
    return await _project(session, item)


async def complete(session: AsyncSession, actor: CurrentUser, item_id: UUID | str,
                   resolution: str, ticket_status: str = "resolved") -> dict:
    item = await _load_item(session, actor, item_id, for_update=True)
    if item.status == "RESOLVED" or item.status == "CLOSED":
        return await _project(session, item)
    if item.status != "IN_PROGRESS":
        raise AppException(ErrorCode.INVALID_STATE, "请先受理人工队列项", http_status=422)
    if item.assignee_id != actor.user_id:
        raise conflict("仅当前受理人可完成人工队列项", ErrorCode.IDEMPOTENCY_CONFLICT)
    item.status = "CLOSED" if ticket_status == "closed" else "RESOLVED"
    ticket = await _linked_ticket(session, item)
    if ticket is not None:
        ticket.status = ticket_status
        context = dict(ticket.context or {})
        context["resolution"] = resolution
        context["resolved_by"] = actor.user_id
        ticket.context = context
        await session.flush()
    return await _project(session, item)
