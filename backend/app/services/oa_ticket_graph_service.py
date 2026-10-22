"""Formal ticket graph projection and server-owned confirmation boundary."""
import logging
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, text

from ..adapters.builtin_gateway import BuiltinGateway
from ..adapters.gateway import BridgeContext
from ..core.context import get_trace_id
from ..core.errors import AppException, ErrorCode
from ..graph.graph_service import extract_interrupt
from ..llm.base import LLMFactory
from ..llm.schemas import TicketExtraction
from ..models.agent_thread import AgentThread
from ..models.human_decision import HumanDecision
from ..models.oa_bridge import OABridgeConfirmation
from ..schemas.oa_ticket import FormalTicketProposal
from ..schemas.ticket_draft import ALLOWED_DRAFT_FIELDS
from ..tools import ticket_tools
from . import oa_ticket_service, ticket_draft_service, audit_service, oa_confirmation_service
from .authorization_service import require_permission
from .oa_command_service import canonical_hash
from .oa_graph_service import actor_for_thread, scene_context

logger = logging.getLogger('oa-agent')


def thread_state(thread):
    return dict(thread_id=str(thread.id), tenant_id=thread.tenant_id, user_id=thread.user_id, scene='ticket')


def operation_key(thread_id):
    return 'ticket-graph:' + str(thread_id)


async def extract(db, state):
    await scene_context(db, state)
    decision = state.get('confirmation') or {}
    draft = await ticket_draft_service.get_draft(db, UUID(state['thread_id']))
    if decision.get('action') == 'edit':
        record = await db.scalar(select(HumanDecision).where(HumanDecision.thread_id == UUID(state['thread_id']),
            HumanDecision.actor_id == state['user_id'], HumanDecision.action == 'edit',
            HumanDecision.id == decision.get('decision_id')))
        if record is None or draft is None:
            raise AppException(ErrorCode.FORBIDDEN, '草稿修改缺少服务端决定', http_status=403)
    else:
        question = next((str(item.get('content', '')) for item in reversed(state.get('messages') or [])
            if item.get('role') == 'user'), '')
        result = await LLMFactory.get_llm().structured([{'role': 'user', 'content': question}], TicketExtraction)
        await scene_context(db, state)
        fields = {key: value for key, value in result.model_dump().items() if key in ALLOWED_DRAFT_FIELDS}
        validate_proposal(state['thread_id'], fields)
        draft = await ticket_draft_service.upsert_draft(db, tenant_id=state['tenant_id'],
            thread_id=UUID(state['thread_id']), user_id=state['user_id'], fields=fields, extracted_fields=fields)
        actor, _ = await scene_context(db, state)
        binding = await oa_ticket_service.prepare(db, actor, validate_proposal(state['thread_id'], fields))
        draft.confirmation_key = binding['confirmation_id']
        await db.commit()
    return dict(ticket_fields=draft.fields, ticket_draft=dict(thread_id=state['thread_id'], fields=draft.fields,
        extracted_fields=draft.extracted_fields, status=draft.status), next_action='waiting_human')


def validate_proposal(thread_id, fields, selection=None):
    try:
        return FormalTicketProposal(operation_id=operation_key(thread_id), thread_id=str(thread_id),
            **fields, **(selection or {}))
    except (ValidationError, TypeError, ValueError):
        raise AppException(ErrorCode.BAD_REQUEST, '工单字段不完整或格式不正确，请修改草稿', http_status=422) from None


async def reviewed_proposal(db, actor, thread, draft):
    binding = await db.scalar(select(OABridgeConfirmation).where(
        OABridgeConfirmation.id == draft.confirmation_key,
        OABridgeConfirmation.tenant_id == actor.tenant_id,
        OABridgeConfirmation.actor_id == actor.user_id,
        OABridgeConfirmation.thread_id == str(thread.id)))
    if binding is None or binding.action not in {'ticket.create', 'ticket.merge'}:
        raise AppException(ErrorCode.INVALID_STATE, '审核内容已失效，请重新核对工单', http_status=409)
    selection = dict(merge_ticket_id=binding.object_id, expected_revision=int(binding.object_version)) if (
        binding.action == 'ticket.merge') else {}
    proposal = validate_proposal(thread.id, draft.fields, selection)
    object_id, version = oa_ticket_service.object_binding(actor, proposal)
    await oa_confirmation_service.binding(db, actor, binding.id, thread_id=str(thread.id),
        action=binding.action, object_id=object_id, object_version=version,
        payload=oa_ticket_service.proposal_values(proposal))
    return proposal, binding


async def reconciled_result(db, state):
    actor, _ = await scene_context(db, state, tool='create_or_merge_ticket')
    decision = state.get('confirmation') or {}
    record = await db.scalar(select(HumanDecision).where(HumanDecision.thread_id == UUID(state['thread_id']),
        HumanDecision.actor_id == actor.user_id, HumanDecision.action == 'confirm',
        HumanDecision.id == decision.get('decision_id')))
    if record is None:
        raise AppException(ErrorCode.FORBIDDEN, '工单尚未由本人确认', http_status=403)
    result = await oa_ticket_service.get_result(db, actor, operation_key(state['thread_id']))
    if not result:
        raise AppException(ErrorCode.INVALID_STATE, '正式工单结果尚未提交，请重新核对', http_status=409)
    current = await oa_ticket_service.detail(db, actor, result['id'])
    return dict(ticket={**current, 'ticket_id': current['id'], 'merged': bool(result.get('merged'))},
        business_id=current['id'], next_action='human')


async def ticket_projection(db, actor, thread):
    draft = await ticket_draft_service.get_draft(db, thread.id)
    result = dict(ticket=None, ticket_fields=None, ticket_draft=None, handoff=None,
        ticket_candidates=[], ticket_review=None)
    if draft:
        result.update(ticket_fields=draft.fields, ticket_draft=dict(thread_id=str(thread.id), fields=draft.fields,
            extracted_fields=draft.extracted_fields, status=draft.status))
        if draft.status == 'PENDING':
            result['ticket_candidates'] = await oa_ticket_service.candidates(db, actor, draft.fields.get('summary', ''))
            if draft.confirmation_key:
                proposal, binding = await reviewed_proposal(db, actor, thread, draft)
                review = dict(mode='merge' if proposal.merge_ticket_id else 'new',
                    target_ticket_id=proposal.merge_ticket_id, expected_revision=proposal.expected_revision,
                    expires_at=binding.expires_at.isoformat(), expired=binding.expires_at <= datetime.now(timezone.utc),
                    changed=False)
                if proposal.merge_ticket_id:
                    target = await oa_ticket_service.detail(db, actor, proposal.merge_ticket_id)
                    review.update(business_no=target['business_no'], summary=target['summary'], state=target['state'],
                        revision=target['revision'], changed=target['revision'] != proposal.expected_revision or (
                            target['state'] not in {'OPEN', 'IN_PROGRESS'}))
                result['ticket_review'] = review
    committed = await oa_ticket_service.get_result(db, actor, operation_key(thread.id))
    if committed:
        current = await oa_ticket_service.detail(db, actor, committed['id'])
        result.update(ticket={**current, 'ticket_id': current['id'], 'merged': bool(committed.get('merged'))}, next_action='human')
    return result


async def resume(db, thread, user, interrupt_id, request, runtime):
    from . import interrupt_service
    # Keep serialization across the domain commit and independent graph writes.
    async with interrupt_service.async_session_factory() as mutex:
        connection = await mutex.connection()
        key = 'formal-ticket:' + str(thread.id)
        await connection.execute(text('SELECT pg_advisory_lock(hashtextextended(:key, 0))'), {'key': key})
        try:
            return await _resume(db, thread, user, interrupt_id, request, runtime)
        finally:
            await connection.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key, 0))'), {'key': key})


async def _resume(db, thread, user, interrupt_id, request, runtime):
    actor, _ = await scene_context(db, thread_state(thread),
        tool='create_or_merge_ticket' if request.action == 'confirm' else 'get_user_context')
    if (actor.user_id, actor.tenant_id) != (user.user_id, user.tenant_id):
        raise AppException(ErrorCode.FORBIDDEN, '只有本人可以确认工单', http_status=403)
    require_permission(actor, 'thread', 'write')
    require_permission(actor, 'ticket', 'write')
    reconcile = request.action == 'reconcile'
    if request.action not in {'confirm', 'edit', 'cancel', 'reconcile'} or request.action != 'edit' and request.edited_data or (
            reconcile and (request.comment or request.idempotency_key)):
        raise AppException(ErrorCode.BAD_REQUEST, '当前工单中断不支持该操作', http_status=422)
    thread = await db.get(AgentThread, thread.id, populate_existing=True)
    digest = canonical_hash(request.model_dump())
    record = await db.scalar(select(HumanDecision).where(HumanDecision.thread_id == thread.id,
        HumanDecision.interrupt_id == interrupt_id, HumanDecision.actor_id == actor.user_id))
    if reconcile and record is None:
        raise AppException(ErrorCode.INVALID_STATE, '尚未保存人工决定，请先确认当前草稿', http_status=409)
    snapshot = await runtime.get_state(thread.id)
    pending = extract_interrupt(snapshot)
    if record:
        if not reconcile and record.payload_hash != digest:
            raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, '重复决定载荷不一致', http_status=409)
        if record.action == 'confirm':
            await scene_context(db, thread_state(thread), tool='create_or_merge_ticket')
            committed = await oa_ticket_service.get_result(db, actor, operation_key(thread.id))
            if not committed:
                raise AppException(ErrorCode.INVALID_STATE, '正式工单结果缺失，请人工核对', http_status=409)
            thread.business_id = committed['id']
        if not pending or pending[0] != interrupt_id:
            thread.current_interrupt_id = pending[0] if pending else None
            thread.status = 'COMPLETED' if record.action == 'cancel' and not pending else 'WAITING_HUMAN'
            thread.error_code = thread.error_msg = None
            await db.commit()
            return thread.status, 'waiting_human' if pending else 'cancelled' if record.action == 'cancel' else 'human'
    else:
        if not pending or pending[0] != interrupt_id or thread.current_interrupt_id != interrupt_id:
            raise AppException(ErrorCode.INTERRUPT_ALREADY_HANDLED, '中断已变化，请刷新后重新确认', http_status=409)
        draft = await ticket_draft_service.get_draft(db, thread.id)
        if draft is None or draft.status != 'PENDING' or draft.tenant_id != actor.tenant_id or draft.user_id != actor.user_id:
            raise AppException(ErrorCode.FORBIDDEN, '当前草稿不可确认', http_status=403)
        if request.action == 'confirm':
            proposal, confirmation = await reviewed_proposal(db, actor, thread, draft)
            gateway = BuiltinGateway(BridgeContext(actor=actor, session=db, trace_id=get_trace_id(),
                confirmation_id=confirmation.id))
            result = await ticket_tools.create_or_merge_ticket(gateway, proposal)
            thread.business_id = result['id']
            draft.status = 'CONFIRMED'
            draft.confirmation_key = operation_key(thread.id)
        elif request.action == 'edit':
            try:
                edited = request.edited_data or {}
                selection_keys = {'merge_ticket_id', 'expected_revision'}
                selection = {key: value for key, value in edited.items() if key in selection_keys}
                fields = {**draft.fields, **ticket_draft_service.validate_draft_fields(
                    {key: value for key, value in edited.items() if key not in selection_keys})}
            except (ValueError, TypeError):
                raise AppException(ErrorCode.BAD_REQUEST, '修改字段不合法', http_status=422) from None
            proposal = validate_proposal(thread.id, fields, selection)
            binding = await oa_ticket_service.prepare(db, actor, proposal)
            draft.fields = fields
            draft.confirmation_key = binding['confirmation_id']
        else:
            draft.status = 'CANCELLED'
        record = HumanDecision(thread_id=thread.id, interrupt_id=interrupt_id, actor_id=actor.user_id,
            action=request.action, comment=request.comment, edited_data=request.edited_data, payload_hash=digest)
        db.add(record)
        await audit_service.audit(db, 'human_decided', thread_id=thread.id, target_type='thread',
            target_id=str(thread.id), input_summary={'action': request.action})
        await db.commit()
    try:
        await runtime.resume(thread.id, dict(action=record.action, decision_id=str(record.id)))
        snapshot = await runtime.get_state(thread.id)
        pending = extract_interrupt(snapshot)
    except Exception:
        logger.warning('正式工单决定已提交，图恢复待重试，thread=%s', thread.id)
        thread.error_code = 'GRAPH_RECOVERY'
        thread.error_msg = '业务决定已保存，请恢复处理'
        thread.status = 'WAITING_HUMAN'
        await db.commit()
        return thread.status, 'human'
    thread.current_interrupt_id = pending[0] if pending else None
    thread.status = 'COMPLETED' if record.action == 'cancel' else 'WAITING_HUMAN'
    thread.error_code = thread.error_msg = None
    await db.commit()
    return thread.status, 'waiting_human' if pending else 'cancelled' if record.action == 'cancel' else 'human'
