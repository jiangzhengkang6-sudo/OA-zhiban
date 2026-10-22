"""
OA 智能体管理系统 - 工单接口路由。

提供工单创建（直接入口，幂等）与状态查询：
    POST /api/tickets
    GET  /api/tickets/{ticket_id}
"""

from fastapi import APIRouter, Depends
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...adapters.factory import get_adapter
from ...adapters.oa_adapter import TicketCommand
from ...core.errors import AppException, ErrorCode, forbidden, not_found
from ...db.session import get_db
from ...models.human_decision import HumanDecision
from ...models.ticket_assignment_rule import TicketAssignmentRule
from ...repositories import thread_repo
from ...repositories import ticket_repo
from ...schemas.common import ok
from ...schemas.ticket import TicketCreateRequest, TicketStatusResponse
from ...schemas.ticket_draft import TicketDraftUpdate, TicketDraftResponse
from ...schemas.support import TicketAssignmentRuleCreate, TicketFeedbackCreate, TicketFeedbackResponse
from ...services.ticket_draft_service import get_draft, upsert_draft
from ...services import ticket_service
from ...services import audit_service
from ...tools import ticket_tools
from ..deps import get_current_user, require_roles

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("/assignment-rules")
async def create_assignment_rule(payload: TicketAssignmentRuleCreate,
                                 session: AsyncSession = Depends(get_db),
                                 user=Depends(require_roles("admin"))):
    rule = TicketAssignmentRule(tenant_id=user.tenant_id, **payload.model_dump())
    session.add(rule)
    await session.commit()
    return ok({
        "rule_id": str(rule.id), "category": rule.category, "impact": rule.impact,
        "queue_id": rule.queue_id, "assignee_id": rule.assignee_id,
        "rule_version": rule.rule_version, "priority": rule.priority, "enabled": rule.enabled,
    })


@router.get("/drafts/{thread_id}")
async def get_ticket_draft(thread_id: UUID, session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    draft = await get_draft(session, thread_id)
    if draft is None or draft.tenant_id != user.tenant_id or draft.user_id != user.user_id:
        raise not_found("工单草稿不存在")
    return ok(TicketDraftResponse(thread_id=str(draft.thread_id), fields=draft.fields,
                                  extracted_fields=draft.extracted_fields or {}, status=draft.status))


@router.patch("/drafts/{thread_id}")
async def update_ticket_draft(thread_id: UUID, payload: TicketDraftUpdate,
                              session: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    draft = await get_draft(session, thread_id)
    if draft is None or draft.tenant_id != user.tenant_id or draft.user_id != user.user_id:
        raise not_found("工单草稿不存在")
    try:
        draft = await upsert_draft(session, tenant_id=user.tenant_id, thread_id=thread_id,
                                   user_id=user.user_id, fields=payload.fields,
                                   extracted_fields=draft.extracted_fields or {})
    except ValueError as exc:
        raise AppException(ErrorCode.BAD_REQUEST, str(exc), http_status=400) from exc
    await session.commit()
    return ok(TicketDraftResponse(thread_id=str(draft.thread_id), fields=draft.fields,
                                  extracted_fields=draft.extracted_fields or {}, status=draft.status))


@router.post("")
async def create_ticket(
    payload: TicketCreateRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """直接创建工单（幂等）。

    Args:
        payload: 工单创建请求。
        session: 数据库会话。
        user: 当前用户。

    Returns:
        ApiResponse: 工单结果。
    """
    if payload.thread_id is None:
        raise AppException(
            ErrorCode.INVALID_STATE,
            "工单必须在用户确认智能助手草稿后创建",
            http_status=422,
        )
    thread = await thread_repo.get_thread(session, payload.thread_id)
    if thread is None:
        raise not_found("会话不存在")
    if thread.user_id != user.user_id or thread.tenant_id != user.tenant_id:
        raise forbidden("无权使用该会话创建工单")
    if payload.idempotency_key != str(thread.id):
        raise AppException(
            ErrorCode.BAD_REQUEST,
            "工单幂等键必须使用会话 ID",
            http_status=400,
        )
    confirmed = await session.scalar(
        select(HumanDecision.id).where(
            HumanDecision.thread_id == thread.id,
            HumanDecision.action == "confirm",
        ).limit(1)
    )
    if confirmed is None:
        raise AppException(
            ErrorCode.INVALID_STATE,
            "工单尚未完成用户确认",
            http_status=422,
        )

    result = await ticket_service.create_or_review(session, user, payload)
    await session.commit()
    return ok(result)


@router.get("/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """查询工单状态与处理进度。

    Args:
        ticket_id: 工单号。
        session: 数据库会话。
        user: 当前用户。

    Returns:
        ApiResponse: 工单信息与时间线。
    """
    try:
        record = await ticket_service.get_authoritative(session, user, ticket_id)
    except AppException as exc:
        if exc.code != ErrorCode.NOT_FOUND:
            raise
        adapter = get_adapter()
        ticket = await ticket_tools.get_ticket_status(adapter, ticket_id, user.user_id)
    else:
        ticket = {
            "ticket_id": record.ticket_id, "category": record.category,
            "priority": record.priority, "impact": record.impact,
            "summary": record.summary, "status": record.status,
            "queue_id": record.queue_id, "assignee_id": record.assignee_id,
            "assignment_rule_version": record.assignment_rule_version,
            "assignment_error": record.assignment_error,
            "merged_from": record.merged_from or [], "user_id": record.user_id,
        }
    timeline = await ticket_repo.list_timeline(session, ticket_id)
    return ok(TicketStatusResponse(ticket=ticket, timeline=timeline))


@router.post("/{ticket_id}/feedback")
async def submit_ticket_feedback(
    ticket_id: str,
    payload: TicketFeedbackCreate,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    result = await ticket_service.submit_feedback(
        session,
        user,
        ticket_id,
        resolved=payload.resolved,
        comment=payload.comment,
        idempotency_key=payload.idempotency_key,
    )
    await session.commit()
    return ok(TicketFeedbackResponse(**result))
