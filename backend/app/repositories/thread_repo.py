"""
OA 智能体管理系统 - 会话数据访问层。

封装 agent_thread / agent_message 的 CRUD 与查询，供 service 层调用。
所有方法接收调用方持有的 AsyncSession。
"""

import hashlib
from datetime import datetime, timezone
from typing import Optional, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.agent_message import AgentMessage
from ..models.agent_thread import AgentThread


async def create_thread(
    session: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    scene: str,
    business_id: Optional[str] = None,
    status: str = "DRAFT",
) -> AgentThread:
    """创建会话主记录。

    Args:
        session: 数据库会话。
        user_id: 用户 ID。
        tenant_id: 租户 ID。
        scene: 场景。
        business_id: 业务单据号。
        status: 初始状态。

    Returns:
        AgentThread: 新创建的会话记录。
    """
    thread = AgentThread(
        user_id=user_id, tenant_id=tenant_id, scene=scene,
        business_id=business_id, status=status,
    )
    session.add(thread)
    await session.flush()
    return thread


async def get_thread(session: AsyncSession, thread_id: UUID) -> Optional[AgentThread]:
    """按 ID 查询会话。

    Args:
        session: 数据库会话。
        thread_id: 会话 ID。

    Returns:
        Optional[AgentThread]: 会话记录，不存在时为 None。
    """
    return await session.get(AgentThread, thread_id)


async def get_thread_by_business(
    session: AsyncSession, business_id: str
) -> Optional[AgentThread]:
    """按业务单据号查询会话（幂等去重用）。

    Args:
        session: 数据库会话。
        business_id: 业务单据号。

    Returns:
        Optional[AgentThread]: 命中的会话，无则 None。
    """
    stmt = select(AgentThread).where(AgentThread.business_id == business_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_thread_by_interrupt_id(
    session: AsyncSession, interrupt_id: str
) -> Optional[AgentThread]:
    """按 pending 中断 ID 反查会话。

    Args:
        session: 数据库会话。
        interrupt_id: HITL 中断 ID。

    Returns:
        Optional[AgentThread]: 命中的会话，无则 None。
    """
    stmt = select(AgentThread).where(
        AgentThread.current_interrupt_id == interrupt_id
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_thread_status(
    session: AsyncSession,
    thread: AgentThread,
    status: str,
    **fields,
) -> AgentThread:
    """更新会话状态及附加字段。

    Args:
        session: 数据库会话。
        thread: 会话记录。
        status: 新状态。
        **fields: 其他需要更新的字段。

    Returns:
        AgentThread: 更新后的会话记录。
    """
    thread.status = status
    for k, v in fields.items():
        setattr(thread, k, v)
    thread.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return thread


async def next_message_seq(session: AsyncSession, thread_id: UUID) -> int:
    """计算会话内下一条消息的序号。

    Args:
        session: 数据库会话。
        thread_id: 会话 ID。

    Returns:
        int: 下一条消息序号（从 1 起）。
    """
    stmt = select(AgentMessage).where(
        AgentMessage.thread_id == thread_id
    ).order_by(AgentMessage.seq.desc()).limit(1)
    result = await session.execute(stmt)
    last = result.scalar_one_or_none()
    return (last.seq + 1) if last else 1


async def add_message(
    session: AsyncSession,
    *,
    thread_id: UUID,
    role: str,
    content: str,
    seq: Optional[int] = None,
    idempotency_key: Optional[str] = None,
) -> AgentMessage:
    """写入一条消息（仅存摘要与哈希）。

    Args:
        session: 数据库会话。
        thread_id: 会话 ID。
        role: 角色。
        content: 消息内容。
        seq: 序号，缺省自动计算。

    Returns:
        AgentMessage: 写入的消息记录。
    """
    if seq is None:
        seq = await next_message_seq(session, thread_id)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    # 摘要截断，避免落长文本
    summary = content[:512] if len(content) > 512 else content
    metadata = {"idempotency_key": idempotency_key} if idempotency_key else None
    msg = AgentMessage(
        thread_id=thread_id, seq=seq, role=role,
        content_summary=summary, content_hash=content_hash,
        full_content=metadata,
    )
    session.add(msg)
    await session.flush()
    return msg


async def get_message_by_idempotency_key(
    session: AsyncSession,
    *,
    thread_id: UUID,
    idempotency_key: str,
) -> Optional[AgentMessage]:
    """按会话和幂等键查找已接收的用户消息。"""
    stmt = select(AgentMessage).where(
        AgentMessage.thread_id == thread_id,
        AgentMessage.full_content["idempotency_key"].as_string() == idempotency_key,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_messages(
    session: AsyncSession, thread_id: UUID
) -> list[AgentMessage]:
    """按序号列出会话消息。

    Args:
        session: 数据库会话。
        thread_id: 会话 ID。

    Returns:
        list[AgentMessage]: 消息列表（按 seq 升序）。
    """
    stmt = (
        select(AgentMessage)
        .where(AgentMessage.thread_id == thread_id)
        .order_by(AgentMessage.seq.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
