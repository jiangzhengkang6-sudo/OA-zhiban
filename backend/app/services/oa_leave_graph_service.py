"""Applicant review of formal leave drafts; the domain owns submission facts."""
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, text

from ..adapters.builtin_gateway import BuiltinGateway
from ..adapters.gateway import BridgeContext
from ..core.context import get_trace_id
from ..core.errors import AppException, ErrorCode
from ..graph.graph_service import extract_interrupt
from ..models.agent_thread import AgentThread
from ..models.human_decision import HumanDecision
from ..models.oa_bridge import OABridgeConfirmation
from ..models.oa_workflow import OAWorkflowOperation
from ..schemas.oa_bridge import BridgeLeaveSubmit
from ..tools import approval_tools
from . import audit_service, oa_confirmation_service, oa_leave_service as leaves
from .authorization_service import require_permission
from .oa_command_service import canonical_hash
from .oa_graph_service import scene_context

logger = logging.getLogger('oa-agent')


def thread_state(thread):
    return dict(thread_id=str(thread.id), user_id=thread.user_id, tenant_id=thread.tenant_id,
        business_id=thread.business_id, scene='leave')


def command(thread, leave, review_route_hash=None):
    return BridgeLeaveSubmit(business_id=leave.id, thread_id=str(thread.id),
        operation_id='leave-graph:' + str(thread.id) + ':' + str(leave.revision),
        expected_revision=leave.revision, requested_submission_version=leave.submission_version + 1,
        review_route_hash=review_route_hash)


async def owned(db, state, *, tool='get_user_context'):
    actor, _ = await scene_context(db, state, tool=tool)
    _, row = await leaves.applicant_access(db, actor, state['business_id'])
    if row.applicant_id != actor.user_id:
        raise AppException(ErrorCode.FORBIDDEN, '只有申请人可以提交请假单', http_status=403)
    return actor, row


async def prepare(state):
    from ..db.session import async_session_factory
    async with async_session_factory() as db:
        actor, row = await owned(db, state)
        leaves.check_editable(row, row.revision)
        thread = await db.get(AgentThread, UUID(state['thread_id']))
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        await scene_context(db, state, tool='get_approval_route')
        route = await gateway.get_approval_route(row.id)
        route_hash = canonical_hash(route)
        payload = command(thread, row, route_hash)
        binding = await oa_confirmation_service.issue(db, actor, thread_id=str(thread.id), action='leave.submit',
            object_id=row.id, object_version=row.revision, payload=payload.model_dump(mode='json'))
        await db.commit()
        return dict(form_snapshot={**row.fields, 'revision': row.revision, 'business_no': row.business_no,
                'review_route_hash': route_hash},
            approval_route=route, human_decision=None, next_action='waiting_human',
            leave_confirmation_id=binding['confirmation_id'])


def gate(state):
    from langgraph.types import interrupt
    decision = interrupt(dict(type='leave_submit', next_action='waiting_human',
        form_snapshot=state.get('form_snapshot'), confirmation_id=state.get('leave_confirmation_id')))
    return dict(human_decision=decision)


async def result_node(state):
    from ..db.session import async_session_factory
    async with async_session_factory() as db:
        actor, row = await owned(db, state, tool='create_or_update_oa_approval')
        decision = state.get('human_decision') or {}
        record = await db.scalar(select(HumanDecision).where(HumanDecision.id == decision.get('decision_id'),
            HumanDecision.thread_id == UUID(state['thread_id']), HumanDecision.actor_id == actor.user_id,
            HumanDecision.action == 'confirm'))
        if record is None:
            raise AppException(ErrorCode.FORBIDDEN, '请假尚未由本人确认', http_status=403)
        await confirmed_result(db, actor, state['thread_id'], row, record)
        return dict(form_snapshot={**row.fields, 'revision': row.revision, 'business_no': row.business_no},
            next_action='completed')


async def confirmed_result(db, actor, thread_id, row, decision):
    saved = decision.edited_data or {}
    binding = await db.scalar(select(OABridgeConfirmation).where(
        OABridgeConfirmation.id == saved.get('confirmation_id'),
        OABridgeConfirmation.thread_id == thread_id, OABridgeConfirmation.actor_id == actor.user_id,
        OABridgeConfirmation.tenant_id == actor.tenant_id, OABridgeConfirmation.action == 'leave.submit',
        OABridgeConfirmation.object_id == row.id))
    operation = await db.scalar(select(OAWorkflowOperation).where(
        OAWorkflowOperation.id == binding.consumed_operation_id,
        OAWorkflowOperation.tenant_id == actor.tenant_id, OAWorkflowOperation.actor_id == actor.user_id,
        OAWorkflowOperation.kind == 'leave.submit', OAWorkflowOperation.target_id == row.id,
        OAWorkflowOperation.operation_id == saved.get('operation_id'))) if binding and binding.consumed_operation_id else None
    gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
    result = await gateway.get_approval_result(saved['operation_id']) if operation else None
    if not result or result.get('id') != row.id or result != operation.result:
        raise AppException(ErrorCode.INVALID_STATE, '正式提交结果缺失，请人工核对', http_status=409)
    return result


def build_graph():
    from langgraph.graph import END, START, StateGraph
    from ..graph.state import LeaveState
    graph = StateGraph(LeaveState)
    graph.add_node('formal_prepare', prepare)
    graph.add_node('formal_confirm', gate)
    graph.add_node('formal_result', result_node)
    graph.add_edge(START, 'formal_prepare')
    graph.add_edge('formal_prepare', 'formal_confirm')
    graph.add_conditional_edges('formal_confirm', lambda state: (state.get('human_decision') or {}).get('action'),
        {'confirm': 'formal_result', 'edit': 'formal_prepare', 'cancel': END})
    graph.add_edge('formal_result', END)
    return graph


async def projection(db, thread):
    _, row = await owned(db, thread_state(thread))
    return dict(form_snapshot={**row.fields, 'revision': row.revision, 'business_no': row.business_no},
        approval_status=row.state, next_action='completed' if thread.status == 'COMPLETED' else 'waiting_human')


async def resume(db, thread, user, interrupt_id, request, runtime):
    from . import interrupt_service
    async with interrupt_service.async_session_factory() as mutex:
        connection = await mutex.connection()
        key = 'formal-leave:' + str(thread.id)
        await connection.execute(text('SELECT pg_advisory_lock(hashtextextended(:key, 0))'), {'key': key})
        try:
            return await _resume(db, thread, user, interrupt_id, request, runtime)
        finally:
            await connection.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key, 0))'), {'key': key})


async def _resume(db, thread, user, interrupt_id, request, runtime):
    state = thread_state(thread)
    actor, row = await owned(db, state,
        tool='create_or_update_oa_approval' if request.action == 'confirm' else 'get_user_context')
    if (actor.user_id, actor.tenant_id) != (user.user_id, user.tenant_id):
        raise AppException(ErrorCode.FORBIDDEN, '只有本人可以确认请假提交', http_status=403)
    require_permission(actor, 'thread', 'write')
    require_permission(actor, 'leave', 'write')
    reconcile = request.action == 'reconcile'
    # Editing belongs to the formal workbench; edit here refreshes the review.
    if request.action not in {'confirm', 'cancel', 'edit', 'reconcile'} or request.edited_data or (
            reconcile and (request.comment or request.idempotency_key)):
        raise AppException(ErrorCode.BAD_REQUEST, '当前请假确认不支持该操作', http_status=422)
    thread = await db.get(AgentThread, thread.id, populate_existing=True)
    digest = canonical_hash(request.model_dump())
    record = await db.scalar(select(HumanDecision).where(HumanDecision.thread_id == thread.id,
        HumanDecision.interrupt_id == interrupt_id, HumanDecision.actor_id == actor.user_id))
    if reconcile and record is None:
        raise AppException(ErrorCode.INVALID_STATE, '尚未保存人工决定，请先确认当前草稿', http_status=409)
    pending = extract_interrupt(await runtime.get_state(thread.id))
    if record:
        if not reconcile and record.payload_hash != digest:
            raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, '重复决定载荷不一致', http_status=409)
        if record.action == 'confirm':
            await scene_context(db, state, tool='create_or_update_oa_approval')
            await confirmed_result(db, actor, str(thread.id), row, record)
        if not pending or pending[0] != interrupt_id:
            thread.current_interrupt_id = pending[0] if pending else None
            thread.status = 'WAITING_HUMAN' if pending else 'COMPLETED'
            thread.error_code = thread.error_msg = None
            await db.commit()
            return thread.status, 'waiting_human' if pending else 'completed'
    else:
        if not pending or pending[0] != interrupt_id or thread.current_interrupt_id != interrupt_id:
            raise AppException(ErrorCode.INTERRUPT_ALREADY_HANDLED, '中断已变化，请刷新后重新确认', http_status=409)
        if request.action == 'confirm':
            confirmation_id = pending[1].get('confirmation_id')
            confirmation = await db.get(OABridgeConfirmation, confirmation_id)
            if confirmation is None or confirmation.object_version != str(row.revision):
                raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, '请假单已被修改，请刷新审核内容后再提交', http_status=409)
            payload = command(thread, row, (pending[1].get('form_snapshot') or {}).get('review_route_hash'))
            gateway = BuiltinGateway(BridgeContext(actor=actor, session=db, trace_id=get_trace_id(),
                confirmation_id=confirmation_id))
            await approval_tools.create_or_update_oa_approval(gateway, payload)
        else:
            binding = await db.get(OABridgeConfirmation, pending[1].get('confirmation_id'))
            if binding and binding.tenant_id == actor.tenant_id and binding.actor_id == actor.user_id:
                binding.expires_at = datetime.now(timezone.utc)
        record = HumanDecision(thread_id=thread.id, interrupt_id=interrupt_id, actor_id=actor.user_id,
            action=request.action, comment=request.comment, payload_hash=digest,
            edited_data={'confirmation_id': confirmation_id, 'operation_id': payload.operation_id}
                if request.action == 'confirm' else None)
        db.add(record)
        await audit_service.audit(db, 'human_decided', thread_id=thread.id, target_type='thread',
            target_id=str(thread.id), input_summary={'action': request.action})
        await db.commit()
    try:
        await runtime.resume(thread.id, dict(action=record.action, decision_id=str(record.id)))
        pending = extract_interrupt(await runtime.get_state(thread.id))
    except Exception:
        logger.warning('正式请假决定已提交，图恢复待重试，thread=%s', thread.id)
        thread.error_code, thread.error_msg = 'GRAPH_RECOVERY', '业务决定已保存，请恢复处理'
        thread.status = 'WAITING_HUMAN'
        await db.commit()
        return thread.status, 'human'
    thread.current_interrupt_id = pending[0] if pending else None
    thread.status = 'WAITING_HUMAN' if pending else 'COMPLETED'
    thread.error_code = thread.error_msg = None
    await db.commit()
    return thread.status, 'waiting_human' if pending else 'completed'
