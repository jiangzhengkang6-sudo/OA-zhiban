"""
OA 智能体管理系统 - 会话服务（接入 LangGraph）。

编排会话创建、消息发送（触发图运行）与状态查询。是 API 层与 graph/repo 的桥梁。
消息发送时同步推进图到结束或下一个中断点，并回写会话状态。
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..adapters.factory import get_adapter
from ..core.context import get_current_user, get_trace_id
from ..core.errors import AppException, ErrorCode, forbidden, not_found
from ..graph.graph_service import extract_interrupt, runtime
from ..llm.compatible import ProviderUnavailable
from ..models.agent_thread import AgentThread
from ..models.leave_application import LeaveApplication
from ..models.leave_application_version import LeaveApplicationVersion
from ..repositories import thread_repo
from ..schemas.thread import ThreadDetail
from ..services.interrupt_service import map_next_action
from ..services.authorization_service import authorize_resource, require_business_identity, require_fresh_identity
from ..services.approval_service import approval_details
from ..services import degradation_service
from ..core.errors import dependency_failed

logger = logging.getLogger("oa-agent")


async def can_view_thread(thread: AgentThread, user, session: AsyncSession | None = None) -> bool:
    """判断当前用户是否可以查看会话详情。

    会话发起人可以查看自己的全部会话；请假审批链中的审批人可以查看
    请假任务详情，但不能因此获得员工消息写入权限。审批人身份以图中
    已生成的 approval_route 为准，避免把同部门的所有请假单暴露给审批人。
    """
    try:
        user = await require_fresh_identity(user, session=session)
        if user.data_scope.get('identity_provider') == 'builtin':
            from .authorization_service import require_permission
            if thread.scene in {'faq', 'ticket', 'leave'}:
                require_permission(user, 'knowledge' if thread.scene == 'faq' else thread.scene, 'read')
                if thread.scene == 'ticket' and thread.business_id:
                    if session is None:
                        return False
                    from .oa_ticket_service import access
                    await access(session, user, thread.business_id, resource='ticket')
                if thread.scene == 'leave':
                    if session is None or not thread.business_id:
                        return False
                    from .oa_leave_service import applicant_access
                    _, leave = await applicant_access(session, user, thread.business_id)
                    if leave.applicant_id != user.user_id:
                        return False
                return thread.tenant_id == user.tenant_id and thread.user_id == user.user_id
            if thread.scene not in {'meeting', 'document', 'email', 'work_task', 'report', 'contract'}:
                return False
            require_permission(user, thread.scene, 'read')
        if thread.scene in {"work_task", "report", "contract"}:
            if session is None:
                return False
            if thread.scene == "contract":
                from .contract_service import _owned
            elif thread.scene == "report":
                from .report_service import _owned
            else:
                from .work_task_service import _batch as _owned
            await _owned(session, user, thread.business_id)
            return True
        if thread.scene in {"document", "email"}:
            await require_business_identity(user, session=session)
            if thread.tenant_id != user.tenant_id or thread.user_id != user.user_id:
                return False
            if session is not None:
                if thread.scene == "document":
                    from .document_service import _owned
                else:
                    from .email_service import _owned
                await _owned(session, user, thread.business_id)
            return True
        if thread.scene == "meeting":
            from .meeting_service import _identity
            user = await _identity(session, user)
            return thread.tenant_id == user.tenant_id and thread.user_id == user.user_id
    except AppException:
        return False
    if session is not None:
        builtin = await session.scalar(select(LeaveApplication.id).where(
            LeaveApplication.thread_id == thread.id).limit(1))
        if builtin:
            from .task_service import can_view_task
            return await can_view_task(session, thread, user)
    if not authorize_resource(user, thread.tenant_id, thread.user_id,
                              required_roles={"approver"} if thread.scene == "leave" else ()).allowed:
        return False
    if thread.user_id == user.user_id:
        return True
    if thread.scene != "leave" or "approver" not in user.roles or not runtime.ready:
        return False

    try:
        snapshot = await runtime.get_state(thread.id)
        state_values = snapshot.values if snapshot else {}
        interrupt = extract_interrupt(snapshot) if snapshot else None
        interrupt_payload = interrupt[1] if interrupt and isinstance(interrupt[1], dict) else {}
        route = state_values.get("approval_route") or interrupt_payload.get("approval_route") or {}
        return any(
            isinstance(node, dict) and node.get("approver_id") == user.user_id
            for node in route.get("nodes", [])
        )
    except Exception as exc:  # 详情读取失败时按无权限处理，避免越权放行
        logger.warning("校验会话审批权限失败: %s", exc)
        return False


async def create_thread(
    session: AsyncSession,
    *,
    scene: str,
    business_id: Optional[str] = None,
) -> AgentThread:
    """创建会话；同一业务单据号已存在则返回已有会话（幂等）。

    Args:
        session: 数据库会话。
        scene: 场景。
        business_id: 业务单据号。

    Returns:
        AgentThread: 会话记录。
    """
    user = get_current_user()
    user = await require_fresh_identity(user, session=session)
    if user.data_scope.get('identity_provider') == 'builtin':
        from .authorization_service import require_permission
        if scene not in {'meeting', 'document', 'email', 'work_task', 'report', 'contract', 'faq', 'ticket', 'leave'}:
            raise AppException(ErrorCode.DEPENDENCY_FAILED, '该智能场景尚未接通正式业务', http_status=503)
        require_permission(user, 'knowledge' if scene == 'faq' else scene, 'read')
    business_id = business_id.strip() if business_id else None
    if user.data_scope.get('identity_provider') == 'builtin' and scene == 'ticket' and business_id:
        raise AppException(ErrorCode.BAD_REQUEST, '请通过工单工作台查看已有工单', http_status=422)

    if scene in {"work_task", "report", "contract"}:
        if not business_id:
            raise AppException(ErrorCode.BAD_REQUEST, "请先通过对应工作台创建业务任务", http_status=422)
        if scene == "contract":
            from .contract_service import _owned
        elif scene == "report":
            from .report_service import _owned
        else:
            from .work_task_service import _batch as _owned
        record = await _owned(session, user, business_id)
        return await session.get(AgentThread, record.thread_id)

    if scene in {"document", "email"}:
        if not business_id:
            raise AppException(ErrorCode.BAD_REQUEST, "请先通过对应工作台创建任务", http_status=422)
        if scene == "document":
            from .document_service import _owned
        else:
            from .email_service import _owned
        record = await _owned(session, user, business_id)
        return await session.get(AgentThread, record.thread_id)

    if scene == "meeting":
        from .meeting_service import _identity, _owned
        await _identity(session, user)
        if not business_id:
            raise AppException(ErrorCode.BAD_REQUEST, "请先通过会议入口提交文本", http_status=400)
        meeting = await _owned(session, user, business_id)
        return await session.get(AgentThread, meeting.thread_id)

    if scene == "leave":
        if not business_id:
            raise AppException(
                ErrorCode.BAD_REQUEST,
                "请先在 OA 中提交完整请假单，并提供请假单号",
                http_status=400,
            )
        if user.data_scope.get('identity_provider') == 'builtin':
            from ..adapters.builtin_gateway import BuiltinGateway
            from ..adapters.gateway import BridgeContext
            case = await BuiltinGateway(BridgeContext(actor=user, session=session)).get_leave_case(business_id)
            if case['applicant_id'] != user.user_id:
                raise forbidden('只有申请人可以提交请假单')
            business_id = case['id']
        else:
            try:
                leave_case = get_adapter().get_leave_case(business_id)
            except TimeoutError:
                raise AppException(ErrorCode.DEPENDENCY_FAILED, "OA 请假单查询超时，请稍后重试", http_status=502)
            if leave_case is None:
                raise not_found("请假单不存在，请先在 OA 中提交完整请假单")
            if leave_case.user_id != user.user_id:
                raise forbidden("无权使用他人的请假单创建会话")

    if business_id:
        existing = await thread_repo.get_thread_by_business(session, business_id)
        if existing is not None:
            if existing.tenant_id != user.tenant_id or existing.user_id != user.user_id:
                raise forbidden("无权访问该业务单据")
            return existing

    return await thread_repo.create_thread(
        session,
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        scene=scene,
        business_id=business_id,
    )


async def send_message(
    session: AsyncSession,
    thread: AgentThread,
    content: str,
    idempotency_key: Optional[str] = None,
) -> tuple[str, str, Optional[str]]:
    from ..core.config import get_settings
    if get_settings().oa_provider == 'builtin' and thread.scene in {'ticket', 'leave'}:
        from sqlalchemy import text
        from . import interrupt_service
        async with interrupt_service.async_session_factory() as mutex:
            connection = await mutex.connection()
            key = 'formal-' + thread.scene + ':' + str(thread.id)
            await connection.execute(text('SELECT pg_advisory_lock(hashtextextended(:key, 0))'), {'key': key})
            try:
                thread = await session.get(AgentThread, thread.id, populate_existing=True)
                return await _send_message(session, thread, content, idempotency_key)
            finally:
                await connection.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key, 0))'), {'key': key})
    return await _send_message(session, thread, content, idempotency_key)


async def _send_message(
    session: AsyncSession,
    thread: AgentThread,
    content: str,
    idempotency_key: Optional[str] = None,
) -> tuple[str, str, Optional[str]]:
    """写入用户消息并同步推进图运行。

    Args:
        session: 数据库会话。
        thread: 会话记录。
        content: 消息内容。

    Returns:
        tuple[str, str, Optional[str]]: (消息 ID, 新状态, next_action)。
    """
    user = get_current_user()
    user = await require_fresh_identity(user, session=session)
    if user.data_scope.get('identity_provider') == 'builtin':
        if not await can_view_thread(thread, user, session):
            raise forbidden('无权使用该智能会话')
        from .authorization_service import require_permission
        require_permission(user, 'thread', 'write')
    if thread.scene in {"document", "email", "work_task", "report", "contract"}:
        await require_business_identity(user, session=session)
        raise AppException(ErrorCode.INVALID_STATE, "请通过对应工作台生成、编辑和确认草稿", http_status=422)
    if thread.scene == "meeting":
        from .meeting_service import _identity
        await _identity(session, user)
        raise AppException(ErrorCode.INVALID_STATE, "请通过会议工作台生成、编辑和确认草稿", http_status=422)
    if idempotency_key:
        existing = await thread_repo.get_message_by_idempotency_key(
            session, thread_id=thread.id, idempotency_key=idempotency_key
        )
        if existing is not None:
            next_action = None
            if runtime.ready:
                snapshot = await runtime.get_state(thread.id)
                next_action = (snapshot.values if snapshot else {}).get("next_action")
            return str(existing.id), thread.status, next_action

    if user.data_scope.get('identity_provider') == 'builtin' and thread.scene in {'ticket', 'leave'} and (
            thread.current_interrupt_id or thread.scene == 'ticket' and thread.business_id or thread.status == 'COMPLETED'):
        raise AppException(ErrorCode.INVALID_STATE, '请先处理当前确认；请勿重复发起业务操作', http_status=409)

    message = await thread_repo.add_message(
        session,
        thread_id=thread.id,
        role="user",
        content=content,
        idempotency_key=idempotency_key,
    )
    await session.commit()

    # Resolve the persisted switch immediately before graph execution. A thread
    # created before the switch is treated as in-flight; newer threads use the
    # new-task policy. Neither branch invokes the model/tool graph.
    degradation = await degradation_service.resolve(session, scene=thread.scene, user=user)
    if degradation is not None:
        in_flight = thread.created_at < degradation.created_at
        action = degradation.inflight_action if in_flight else degradation.new_task_action
        if action == "pause":
            await thread_repo.update_thread_status(
                session,
                thread,
                "PAUSED",
                error_code=ErrorCode.DEGRADED.value,
                error_msg=degradation.reason,
            )
            await session.commit()
            return str(message.id), thread.status, "degraded"
        if action == "reject":
            await thread_repo.update_thread_status(
                session,
                thread,
                "PAUSED",
                error_code=ErrorCode.DEGRADED.value,
                error_msg=degradation.reason,
            )
            await session.commit()
            raise dependency_failed("当前场景处于降级状态，请稍后重试", {"reason": degradation.reason})
        if action == "fallback":
            await thread_repo.update_thread_status(
                session,
                thread,
                "WAITING_HUMAN",
                error_code=ErrorCode.DEGRADED.value,
                error_msg=degradation.reason,
            )
            await session.commit()
            return str(message.id), thread.status, "human"

    # 构造图输入状态
    input_state = {
        "thread_id": str(thread.id),
        "user_id": user.user_id,
        "tenant_id": user.tenant_id,
        "scene": thread.scene,
        "business_id": thread.business_id,
        "trace_id": get_trace_id(),
        "messages": [{"role": "user", "content": content}],
    }

    try:
        result = await runtime.invoke(thread.id, input_state)
    except ProviderUnavailable:
        error_msg = "模型服务暂不可用或响应超时，请稍后重试"
        await thread_repo.update_thread_status(
            session, thread, "PAUSED",
            error_code=ErrorCode.DEPENDENCY_FAILED.value, error_msg=error_msg,
        )
        await session.commit()
        raise dependency_failed(error_msg) from None
    next_action = result.get("next_action")
    status = map_next_action(next_action)

    # 回写会话状态
    await thread_repo.update_thread_status(
        session,
        thread,
        status,
        intent=result.get("intent", thread.intent),
        business_id=result.get("business_id") or thread.business_id,
        error_code=(result.get("error") or {}).get("code"),
        error_msg=(result.get("error") or {}).get("msg"),
    )

    # 检测 pending interrupt
    snapshot = await runtime.get_state(thread.id)
    interrupt = extract_interrupt(snapshot)
    if interrupt is not None:
        interrupt_payload = interrupt[1] if isinstance(interrupt[1], dict) else {}
        next_action = next_action or interrupt_payload.get("next_action") or "human"
        thread.current_interrupt_id = interrupt[0]
        await thread_repo.update_thread_status(
            session, thread, "WAITING_HUMAN", current_interrupt_id=interrupt[0]
        )
        # 记录进入等待的时间，供催办升级调度器使用
        thread.waiting_since = datetime.now(timezone.utc)
    await session.commit()
    return str(message.id), thread.status, next_action


async def build_thread_detail(
    session: AsyncSession, thread: AgentThread
) -> ThreadDetail:
    """构造会话状态详情（合并图状态与业务表）。

    Args:
        session: 数据库会话。
        thread: 会话记录。

    Returns:
        ThreadDetail: 会话详情。
    """
    if thread.scene in {"work_task", "report", "contract"}:
        return ThreadDetail(thread_id=str(thread.id), scene=thread.scene, status=thread.status,
            business_id=thread.business_id, next_action="workbench", messages=[],
            created_at=thread.created_at, updated_at=thread.updated_at)
    messages = await thread_repo.list_messages(session, thread.id)
    state_values: dict = {}
    interrupt_payload: dict = {}
    if runtime.ready:
        try:
            snapshot = await runtime.get_state(thread.id)
            state_values = snapshot.values if snapshot else {}
            interrupt = extract_interrupt(snapshot)
            if interrupt is not None and isinstance(interrupt[1], dict):
                interrupt_payload = interrupt[1]
        except Exception as exc:  # 图状态读取失败不阻断详情
            logger.warning("读取图状态失败: %s", exc)

    # 子图 interrupt 时业务字段可能未写回父图 state，故从 interrupt payload 兜底
    from ..core.config import get_settings
    if get_settings().oa_provider == 'builtin' and thread.scene == 'faq':
        from .oa_graph_service import actor_for_thread, validate_cached_answer
        actor = await actor_for_thread(session, dict(thread_id=str(thread.id), tenant_id=thread.tenant_id,
            user_id=thread.user_id, scene=thread.scene))
        if state_values.get('answer'):
            try:
                await validate_cached_answer(session, actor, state_values['answer'])
            except AppException:
                state_values = {**state_values, 'answer': None, 'faq_chunks': [], 'handoff': None,
                    'next_action': 'human', 'error': {'code': 'SOURCE_REVOKED', 'msg': '引用知识已失效或权限已变化，请重新提问'}}
    if get_settings().oa_provider == 'builtin' and thread.scene == 'ticket':
        from .oa_graph_service import actor_for_thread
        from .oa_ticket_graph_service import ticket_projection
        actor = await actor_for_thread(session, dict(thread_id=str(thread.id), tenant_id=thread.tenant_id,
            user_id=thread.user_id, scene='ticket'))
        state_values.update(await ticket_projection(session, actor, thread))
        interrupt_payload = {}
    if get_settings().oa_provider == 'builtin' and thread.scene == 'leave':
        from .oa_leave_graph_service import projection
        return ThreadDetail(thread_id=str(thread.id), scene='leave', status=thread.status,
            business_id=thread.business_id, current_interrupt_id=thread.current_interrupt_id,
            messages=[dict(role=m.role, summary=m.content_summary, seq=m.seq) for m in messages],
            error=dict(code=thread.error_code, msg=thread.error_msg) if thread.error_code else None,
            created_at=thread.created_at, updated_at=thread.updated_at,
            **await projection(session, thread))
    precheck = state_values.get("precheck") or interrupt_payload.get("precheck")
    approval_route = state_values.get("approval_route") or interrupt_payload.get("approval_route")
    ticket_fields = state_values.get("ticket_fields") or interrupt_payload.get("ticket_fields")

    approval = await approval_details(session, thread.id) if thread.scene == "leave" else {}
    application = None
    if thread.scene == "leave":
        application = (await session.scalars(select(LeaveApplication).where(
            LeaveApplication.thread_id == thread.id).limit(1))).one_or_none()
    form_snapshot = state_values.get("form_snapshot") or interrupt_payload.get("form_snapshot")
    if application:
        version = (await session.scalars(select(LeaveApplicationVersion).where(
            LeaveApplicationVersion.application_id == application.id,
            LeaveApplicationVersion.version == application.current_version))).one_or_none()
        form_snapshot = {**application.latest_fields, "user_id": application.user_id,
                         "business_id": application.business_id}
        saved = version.precheck_result if version else None
        precheck = ({**saved, "results": saved.get("results", saved.get("items", []))}
                    if saved else None)
        instance = await approval_details(session, thread.id)
        approval_route = {"business_id": thread.business_id,
                          "nodes": instance.get("approval_nodes", []),
                          "risk_hint": "", "conflict": False}
    legacy_warning = (thread.scene == "leave" and thread.status == "WAITING_HUMAN"
                      and not thread.current_interrupt_id and not approval)
    return ThreadDetail(
        thread_id=str(thread.id),
        scene=thread.scene,
        status=thread.status,
        intent=thread.intent or state_values.get("intent"),
        business_id=thread.business_id,
        application_id=str(application.id) if application else None,
        current_interrupt_id=thread.current_interrupt_id,
        next_action=state_values.get("next_action") or thread.status,
        messages=[
            {"role": m.role, "summary": m.content_summary, "seq": m.seq}
            for m in messages
        ],
        precheck=precheck,
        form_snapshot=form_snapshot,
        approval_route=approval_route,
        **approval,
        human_decision=state_values.get("human_decision"),
        answer=state_values.get("answer"),
        ticket=state_values.get("ticket"),
        ticket_fields=ticket_fields,
        ticket_draft=state_values.get("ticket_draft"),
        ticket_candidates=state_values.get('ticket_candidates') or [],
        ticket_review=state_values.get('ticket_review'),
        handoff=state_values.get("handoff"),
        error=({"code": "LEGACY_RECONCILE", "msg": "旧请假任务缺少待办中断，需人工核对权威审批结果；系统不会自动补批"}
               if legacy_warning else state_values.get("error"))
        or ({"code": thread.error_code, "msg": thread.error_msg} if thread.error_code else None),
        created_at=thread.created_at,
        updated_at=thread.updated_at,
    )
