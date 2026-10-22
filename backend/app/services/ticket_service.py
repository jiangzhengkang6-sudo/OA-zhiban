"""Authoritative built-in ticket operations and deterministic assignment."""

import hashlib
import json
import re
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..adapters.factory import get_adapter
from ..adapters.oa_adapter import TicketCommand
from ..core.context import CurrentUser
from ..core.errors import AppException, ErrorCode, forbidden, not_found
from ..models.ticket_assignment_rule import TicketAssignmentRule
from ..models.human_queue_item import HumanQueueItem
from ..models.ticket_feedback import TicketFeedback
from ..models.ticket_record import TicketRecord
from ..schemas.support import TicketDuplicateCandidate, TicketOperationResponse
from ..schemas.ticket import TicketCreateRequest
from ..tools import ticket_tools
from .handoff_service import ensure_handoff


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip().lower())


def duplicate_score(summary: str, candidate_summary: str) -> tuple[float, str] | None:
    """Return a deterministic duplicate score/reason, or None."""
    left, right = _normalize(summary), _normalize(candidate_summary)
    if not left or not right:
        return None
    if left == right:
        return 1.0, "摘要完全一致"
    left_tokens, right_tokens = set(left), set(right)
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    return (round(overlap, 3), "摘要关键词高度重合") if overlap >= 0.7 else None


def _hash_payload(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _response(row: TicketRecord | None, *, status: str | None = None, candidates=None, merged=False) -> dict:
    if row is None:
        return TicketOperationResponse(status=status or "DUPLICATE_REVIEW",
                                      duplicate_candidates=candidates or [], merged=merged).model_dump()
    return TicketOperationResponse(ticket_id=row.ticket_id, status=status or row.status,
        category=row.category, priority=row.priority, impact=row.impact, summary=row.summary,
        queue_id=row.queue_id, assignee_id=row.assignee_id,
        assignment_rule_version=row.assignment_rule_version, assignment_error=row.assignment_error,
        merged=merged, duplicate_candidates=candidates or []).model_dump()


async def _candidates(session: AsyncSession, actor: CurrentUser, payload: TicketCreateRequest) -> list[TicketDuplicateCandidate]:
    rows = (await session.scalars(select(TicketRecord).where(
        TicketRecord.tenant_id == actor.tenant_id, TicketRecord.user_id == actor.user_id,
        TicketRecord.status.in_(("open", "in_progress"))
    ).order_by(TicketRecord.updated_at.desc()))).all()
    result = []
    for row in rows:
        score = duplicate_score(payload.summary, row.summary)
        if score:
            result.append(TicketDuplicateCandidate(ticket_id=row.ticket_id, score=score[0], reason=score[1], status=row.status))
    return sorted(result, key=lambda item: item.score, reverse=True)


async def _assignment(session: AsyncSession, actor: CurrentUser, category: str, impact: str):
    rules = (await session.scalars(select(TicketAssignmentRule).where(
        TicketAssignmentRule.tenant_id == actor.tenant_id, TicketAssignmentRule.enabled.is_(True)
    ).order_by(TicketAssignmentRule.priority.desc()))).all()
    exact = [r for r in rules if r.category in (category, "*") and r.impact in (impact, "*")]
    if not exact:
        return None
    return sorted(exact, key=lambda r: (r.category == category, r.impact == impact, r.priority), reverse=True)[0]


async def create_or_review(session: AsyncSession, actor: CurrentUser, payload: TicketCreateRequest) -> dict:
    raw = payload.model_dump(mode="json")
    payload_hash = _hash_payload({k: v for k, v in raw.items() if k != "merge_ticket_id"})
    existing = (await session.scalars(select(TicketRecord).where(
        TicketRecord.tenant_id == actor.tenant_id, TicketRecord.idempotency_key == payload.idempotency_key
    ).with_for_update())).one_or_none()
    if existing:
        if existing.payload_hash != payload_hash:
            raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "同一工单幂等键的载荷不能变更", http_status=409)
        return _response(existing, merged=bool(payload.merge_ticket_id))

    duplicate_candidates = await _candidates(session, actor, payload)
    if duplicate_candidates and not payload.merge_ticket_id:
        return _response(None, candidates=duplicate_candidates)

    merged = False
    target = None
    if payload.merge_ticket_id:
        target = (await session.scalars(select(TicketRecord).where(
            TicketRecord.ticket_id == payload.merge_ticket_id, TicketRecord.tenant_id == actor.tenant_id
        ).with_for_update())).one_or_none()
        if target is None or target.user_id != actor.user_id:
            raise forbidden("无权合并该工单")
        if target.status not in {"open", "in_progress"}:
            raise AppException(ErrorCode.INVALID_STATE, "目标工单当前不可合并", http_status=422)
        merged_from = list(target.merged_from or [])
        source = str(payload.thread_id)
        if source not in merged_from:
            merged_from.append(source)
            target.merged_from = merged_from
        merged = True
        await session.flush()
        return _response(target, candidates=duplicate_candidates, merged=merged)

    rule = await _assignment(session, actor, payload.category, payload.context.get("impact", "个人"))
    assignment_error = None if rule else {"code": "NO_ASSIGNMENT_RULE", "msg": "暂未匹配到有效分派规则，工单待人工领取"}
    command = TicketCommand(idempotency_key=payload.idempotency_key, category=payload.category,
        priority=payload.priority, impact=payload.context.get("impact", "个人"), summary=payload.summary,
        context=payload.context, user_id=actor.user_id, queue_id=rule.queue_id if rule else "")
    result = await ticket_tools.create_or_merge_ticket(get_adapter(), command)
    row = TicketRecord(tenant_id=actor.tenant_id, ticket_id=result["ticket_id"] or f"TK-{uuid4().hex[:10].upper()}",
        thread_id=payload.thread_id, user_id=actor.user_id, category=payload.category, priority=payload.priority,
        impact=command.impact, summary=payload.summary, status="open", queue_id=rule.queue_id if rule else None,
        assignee_id=rule.assignee_id if rule else None, assignment_rule_version=rule.rule_version if rule else None,
        assignment_error=assignment_error, merged_from=[], context=payload.context,
        idempotency_key=payload.idempotency_key, payload_hash=payload_hash)
    session.add(row)
    await session.flush()
    return _response(row)


async def get_authoritative(session: AsyncSession, actor: CurrentUser, ticket_id: str) -> TicketRecord:
    row = await session.scalar(select(TicketRecord).where(TicketRecord.ticket_id == ticket_id))
    if row is None:
        raise not_found("工单不存在")
    if row.tenant_id != actor.tenant_id or (row.user_id != actor.user_id and "cs" not in actor.roles and "admin" not in actor.roles):
        raise forbidden("无权查看该工单")
    return row


async def submit_feedback(session: AsyncSession, actor: CurrentUser, ticket_id: str,
                          *, resolved: bool, comment: str, idempotency_key: str) -> dict:
    """Record feedback once and reopen negative feedback into human review."""
    payload = {"resolved": resolved, "comment": comment}
    payload_hash = _hash_payload(payload)
    existing = await session.scalar(select(TicketFeedback).where(
        TicketFeedback.tenant_id == actor.tenant_id,
        TicketFeedback.idempotency_key == idempotency_key,
    ).with_for_update())
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "同一反馈幂等键的载荷不能变更", http_status=409)
        review_item = None
        if not existing.resolved and existing.thread_id is not None:
            review_item = await session.scalar(select(HumanQueueItem).where(
                HumanQueueItem.tenant_id == actor.tenant_id,
                HumanQueueItem.thread_id == existing.thread_id,
                HumanQueueItem.reason_code == "NEGATIVE_FEEDBACK",
                HumanQueueItem.status == "OPEN",
            ).limit(1))
        ticket = await session.scalar(select(TicketRecord).where(
            TicketRecord.tenant_id == actor.tenant_id,
            TicketRecord.ticket_id == existing.ticket_id,
        ))
        return {
            "feedback_id": str(existing.id),
            "ticket_id": existing.ticket_id,
            "ticket_status": ticket.status if ticket else None,
            "review_queue_item_id": str(review_item.id) if review_item else None,
            "resolved": existing.resolved,
        }

    ticket = await session.scalar(select(TicketRecord).where(
        TicketRecord.tenant_id == actor.tenant_id,
        TicketRecord.ticket_id == ticket_id,
    ).with_for_update())
    if ticket is None:
        raise not_found("工单不存在")
    if ticket.user_id != actor.user_id:
        raise forbidden("仅工单发起人可以提交反馈")
    if ticket.status not in {"resolved", "closed"}:
        raise AppException(ErrorCode.INVALID_STATE, "工单尚未进入可反馈状态", http_status=422)

    feedback = TicketFeedback(
        tenant_id=actor.tenant_id,
        ticket_id=ticket.ticket_id,
        thread_id=ticket.thread_id,
        user_id=actor.user_id,
        resolved=resolved,
        comment=comment,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
    )
    session.add(feedback)
    ticket.status = "closed" if resolved else "open"
    review_item = None
    if not resolved and ticket.thread_id is not None:
        review_item = await ensure_handoff(
            session,
            tenant_id=actor.tenant_id,
            thread_id=ticket.thread_id,
            user_id=ticket.user_id,
            scene="ticket",
            reason_code="NEGATIVE_FEEDBACK",
            context={"summary": ticket.summary, "feedback": comment, "ticket_id": ticket.ticket_id},
        )
    await session.flush()
    return {
        "feedback_id": str(feedback.id),
        "ticket_id": ticket.ticket_id,
        "ticket_status": ticket.status,
        "review_queue_item_id": str(review_item.id) if review_item else None,
        "resolved": resolved,
    }
