"""
OA 智能体管理系统 - 工单数据访问层。

提供工单上下文的查询与时间线组装（基于审计事件）。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.audit_event import AuditEvent
from ..models.ticket_context import TicketContext


async def get_ticket_context(
    session: AsyncSession, ticket_id: str
) -> Optional[TicketContext]:
    """按工单号查询工单上下文快照。

    Args:
        session: 数据库会话。
        ticket_id: 工单号。

    Returns:
        Optional[TicketContext]: 工单上下文，无则 None。
    """
    stmt = select(TicketContext).where(TicketContext.ticket_id == ticket_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_timeline(session: AsyncSession, ticket_id: str) -> list[dict]:
    """组装工单处理时间线（基于工单相关审计事件）。

    Args:
        session: 数据库会话。
        ticket_id: 工单号。

    Returns:
        list[dict]: 时间线事件列表。
    """
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.business_id == ticket_id)
        .order_by(AuditEvent.created_at.asc())
    )
    result = await session.execute(stmt)
    return [
        {
            "action": e.action,
            "result": e.result,
            "actor_id": e.actor_id,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in result.scalars().all()
    ]