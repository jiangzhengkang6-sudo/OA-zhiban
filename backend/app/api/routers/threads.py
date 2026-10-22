"""
OA 智能体管理系统 - 会话接口路由。

提供智能助手会话的创建、消息发送与状态查询：
    POST /api/agent/threads
    POST /api/agent/threads/{id}/messages
    GET  /api/agent/threads/{id}
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.context import get_trace_id
from ...core.errors import AppException, ErrorCode, not_found
from ...db.session import get_db
from ...repositories import thread_repo
from ...schemas.common import ok
from ...schemas.thread import (
    MessageCreateRequest,
    MessageResponse,
    ThreadCreateRequest,
    ThreadResponse,
)
from ...services import thread_service
from ..deps import get_current_user

router = APIRouter(prefix="/agent/threads", tags=["agent-threads"])


@router.post("")
async def create_thread(
    payload: ThreadCreateRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """创建智能体会话。

    Args:
        payload: 创建请求（场景+可选业务单据号）。
        session: 数据库会话。
        user: 当前登录用户。

    Returns:
        ApiResponse: 含 thread_id 与状态。
    """
    thread = await thread_service.create_thread(
        session, scene=payload.scene, business_id=payload.business_id
    )
    await session.commit()
    return ok(
        ThreadResponse(
            thread_id=str(thread.id),
            status=thread.status,
            business_id=thread.business_id,
        )
    )


@router.post("/{thread_id}/messages")
async def send_message(
    thread_id: UUID,
    payload: MessageCreateRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """发送消息并启动/恢复图运行。

    Args:
        thread_id: 会话 ID。
        payload: 消息内容与幂等键。
        session: 数据库会话。
        user: 当前登录用户。

    Returns:
        ApiResponse: 含 message_id、状态与 trace_id。
    """
    thread = await thread_repo.get_thread(session, thread_id)
    if thread is None:
        raise not_found("会话不存在")
    if thread.user_id != user.user_id or thread.tenant_id != user.tenant_id:
        raise AppException(ErrorCode.FORBIDDEN, "无权访问该会话", http_status=403)

    message_id, status, next_action = await thread_service.send_message(
        session, thread, payload.content, payload.idempotency_key
    )
    return ok(
        MessageResponse(
            message_id=message_id,
            status=status,
            trace_id=get_trace_id(),
            next_action=next_action,
        )
    )


@router.get("/{thread_id}")
async def get_thread(
    thread_id: UUID,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """查询会话状态详情。

    Args:
        thread_id: 会话 ID。
        session: 数据库会话。
        user: 当前登录用户。

    Returns:
        ApiResponse: 会话详情。
    """
    thread = await thread_repo.get_thread(session, thread_id)
    if thread is None:
        raise not_found("会话不存在")
    if not await thread_service.can_view_thread(thread, user, session):
        raise AppException(ErrorCode.FORBIDDEN, "无权访问该会话", http_status=403)

    detail = await thread_service.build_thread_detail(session, thread)
    return ok(detail)
