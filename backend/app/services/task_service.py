"""Server-side task projections and resource-scoped task actions."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..adapters.factory import get_adapter
from ..core.context import CurrentUser
from ..core.enums import ErrorCode, ThreadStatus
from ..core.errors import AppException, not_found
from ..graph.graph_service import extract_interrupt, runtime
from ..models.agent_thread import AgentThread
from ..models.approval_instance import ApprovalInstance
from ..models.approval_node import ApprovalNode
from ..models.human_queue_item import HumanQueueItem
from ..schemas.task import TaskPage, TaskResponsibility, TaskSummary
from ..repositories import thread_repo
from ..services import approval_service
from ..services.authorization_service import require_business_identity, require_fresh_identity
from ..services.handoff_service import ensure_handoff
from ..services.interrupt_service import map_next_action


def _approval_scope(actor: CurrentUser):
    return select(ApprovalInstance.thread_id).join(ApprovalNode, ApprovalNode.instance_id == ApprovalInstance.id).where(
        ApprovalInstance.tenant_id == actor.tenant_id,
        ApprovalNode.approver_id == actor.user_id,
        ApprovalNode.status == "ACTIVE",
        ApprovalInstance.status == "ACTIVE",
    )


def _visible_clause(actor: CurrentUser):
    owner = AgentThread.user_id == actor.user_id
    from ..models.contract_record import ContractRecord
    contracts = select(ContractRecord.thread_id).where(ContractRecord.tenant_id == actor.tenant_id,
        ContractRecord.reviewer_id == actor.user_id)
    reviewer = and_(AgentThread.scene == "contract", AgentThread.id.in_(contracts)) if set(actor.roles).intersection(
        {"approver", "admin"}) else AgentThread.id.is_(None)
    if "admin" in actor.roles and actor.data_scope.get("all"):
        return AgentThread.tenant_id == actor.tenant_id
    approver = and_(AgentThread.scene == "leave", AgentThread.id.in_(_approval_scope(actor)))
    return and_(AgentThread.tenant_id == actor.tenant_id, or_(owner, approver, reviewer))


async def _load_thread(session: AsyncSession, task_id: UUID, actor: CurrentUser) -> AgentThread:
    thread = await session.get(AgentThread, task_id)
    if thread is None or not await can_view_task(session, thread, actor):
        raise AppException(ErrorCode.FORBIDDEN if thread else ErrorCode.NOT_FOUND,
                           "无权访问该任务" if thread else "任务不存在",
                           http_status=403 if thread else 404)
    return thread


async def can_view_task(session: AsyncSession, thread: AgentThread, actor: CurrentUser) -> bool:
    actor = await require_fresh_identity(actor, session=session)
    if actor.data_scope.get('identity_provider') == 'builtin':
        from .authorization_service import require_permission
        if thread.scene not in {'meeting', 'document', 'email', 'work_task', 'report', 'contract'}:
            return False
        try:
            require_permission(actor, thread.scene, 'read')
        except AppException:
            return False
    if thread.scene in {"document", "email"}:
        await require_business_identity(actor, session=session)
    if thread.scene == "meeting":
        from .meeting_service import _identity
        actor = await _identity(session, actor)
    if thread.tenant_id != actor.tenant_id:
        return False
    if thread.scene in {"work_task", "report", "contract"}:
        await require_business_identity(actor, session=session)
        if "admin" in actor.roles and actor.data_scope.get("all"):
            return True
        if thread.scene == "contract":
            from ..models.contract_record import ContractRecord
            record = await session.scalar(select(ContractRecord).where(ContractRecord.thread_id == thread.id))
            return bool(record and (record.owner_id == actor.user_id or record.reviewer_id == actor.user_id
                and set(actor.roles).intersection({"approver", "admin"})))
        return thread.user_id == actor.user_id
    if thread.user_id == actor.user_id:
        return True
    if "admin" in actor.roles and actor.data_scope.get("all"):
        return True
    if thread.scene != "leave" or "approver" not in actor.roles:
        return False
    current = await approval_service.active_node(session, thread.id)
    return current is not None and current.approver_id == actor.user_id


async def _project(session: AsyncSession, thread: AgentThread, actor: CurrentUser) -> TaskSummary:
    if thread.scene in {"work_task", "report", "contract"}:
        if thread.scene == "contract":
            from ..models.contract_record import ContractRecord as Record
            from .contract_service import _actions
        elif thread.scene == "report":
            from ..models.report_record import ReportRecord as Record
            from .report_service import _actions
        else:
            from ..models.work_task_batch import WorkTaskBatch as Record
        record = await session.scalar(select(Record).where(Record.thread_id == thread.id,
            Record.tenant_id == actor.tenant_id))
        if record is None:
            raise not_found("任务不存在")
        owned = record.owner_id == actor.user_id
        if thread.scene == "contract":
            actions = _actions(record, actor)
            responsibility = TaskResponsibility(role="reviewer", user_id=record.reviewer_id)
        elif thread.scene == "report":
            actions = _actions(record.status) if owned else []
            responsibility = TaskResponsibility(role="owner", user_id=record.owner_id)
        else:
            actions = {"CREATED": ["extract"], "DRAFT_READY": ["edit", "confirm", "reject"],
                "PAUSED": ["retry"]}.get(record.status, []) if owned else []
            responsibility = TaskResponsibility(role="owner", user_id=record.owner_id)
        return TaskSummary(task_id=str(thread.id), task_type=thread.scene, business_id=thread.business_id,
            business_status=record.status, next_action="workbench", responsibility=responsibility,
            available_actions=actions, pause_reason={"message": "任务已暂停，请在工作台查看"}
            if record.status == "PAUSED" else None, created_at=record.created_at, updated_at=record.updated_at)
    if thread.scene in {"document", "email"}:
        if thread.scene == "document":
            from ..models.document_record import DocumentRecord as Record
            from .document_service import _actions
        else:
            from ..models.email_record import EmailRecord as Record
            from .email_service import _actions
        record = await session.scalar(select(Record).where(Record.thread_id == thread.id,
                                                         Record.tenant_id == actor.tenant_id))
        if record is None:
            raise not_found("任务不存在")
        return TaskSummary(task_id=str(thread.id), task_type=thread.scene, business_id=thread.business_id,
            business_status=record.status,
            next_action={"CREATED": "generate" if thread.scene == "document" else "analyze",
                         "DRAFT_READY": "review", "REVIEWING": "review", "PAUSED": "paused",
                         "CONFIRMED": "completed", "REJECTED": "rejected"}.get(record.status, "processing"),
            responsibility=TaskResponsibility(role="owner", user_id=thread.user_id),
            available_actions=_actions(record.status) if thread.user_id == actor.user_id else [],
            pause_reason={"code": record.error_code, "trace_id": record.error_trace_id,
                          "message": record.error_message} if record.status == "PAUSED" else None,
            created_at=record.created_at, updated_at=record.updated_at)
    if thread.scene == "meeting":
        from ..models.meeting_record import MeetingRecord
        from .meeting_service import _actions, _identity
        actor = await _identity(session, actor)
        record = await session.scalar(select(MeetingRecord).where(MeetingRecord.thread_id == thread.id))
        if record is None:
            raise not_found("会议任务不存在")
        return TaskSummary(
            task_id=str(thread.id), task_type="meeting", business_id=record.meeting_id,
            business_status=record.status,
            next_action={"CREATED": "generate", "DRAFT_READY": "review", "REVIEWING": "review",
                         "PAUSED": "paused", "CONFIRMED": "completed", "REJECTED": "rejected"}.get(record.status, "processing"),
            responsibility=TaskResponsibility(role="owner", user_id=thread.user_id),
            available_actions=_actions(record.status) if thread.user_id == actor.user_id else [],
            pause_reason={"code": record.error_code, "trace_id": record.error_trace_id,
                          "message": record.error_message} if record.status == "PAUSED" else None,
            created_at=record.created_at, updated_at=record.updated_at,
        )
    from .thread_service import build_thread_detail

    detail = await build_thread_detail(session, thread)
    next_action = detail.next_action
    if next_action == thread.status:
        next_action = {"WAITING_HUMAN": "human", "PAUSED": "paused",
                       "APPROVED": "approved", "REJECTED": "rejected",
                       "COMPLETED": "completed"}.get(thread.status, next_action)
    responsibility = TaskResponsibility(role="owner", user_id=thread.user_id)
    actions: list[str] = []
    active = detail.active_approval_node if detail else None
    if active:
        responsibility = TaskResponsibility(
            role="approver", user_id=active.get("approver_id"),
            display_name=active.get("approver_name"),
            waiting_since=active.get("waiting_since"),
        )
        if active.get("approver_id") == actor.user_id:
            actions.extend(["approve", "edit", "reject"])
    if thread.user_id == actor.user_id and thread.status not in {"APPROVED", "REJECTED", "COMPLETED"}:
        actions.append("continue")
        if thread.status != "PAUSED":
            actions.append("handoff")
    if thread.status == "PAUSED" and detail.approval_recovery_action:
        if detail.approval_recovery_action not in actions:
            actions.append(detail.approval_recovery_action)
    return TaskSummary(
        task_id=str(thread.id), task_type=thread.scene, business_id=thread.business_id,
        business_status=thread.status, next_action=next_action,
        responsibility=responsibility, available_actions=actions,
        pause_reason=detail.error if thread.status == "PAUSED" else None,
        created_at=thread.created_at, updated_at=thread.updated_at,
    )


async def list_tasks(session: AsyncSession, actor: CurrentUser, *, page: int = 1, page_size: int = 20,
                     scene: Optional[str] = None, status: Optional[str] = None,
                     updated_after: Optional[datetime] = None, updated_before: Optional[datetime] = None,
                     inbox: bool = False) -> TaskPage:
    actor = await require_fresh_identity(actor, session=session)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    conditions = [_visible_clause(actor)]
    if actor.data_scope.get('identity_provider') == 'builtin':
        scenes = [p['resource'] for p in actor.data_scope.get('permissions', []) if p['action'] == 'read']
        conditions.append(AgentThread.scene.in_(set(scenes) & {'meeting', 'document', 'email', 'work_task', 'report', 'contract'}))
    if actor.data_scope.get('identity_provider') != 'builtin' and not set(actor.roles).intersection({"employee", "approver", "admin", "ops"}):
        conditions.append(AgentThread.scene.notin_(["document", "email", "work_task", "report", "contract"]))
    if inbox:
        conditions.extend([AgentThread.scene == 'leave', AgentThread.status == 'WAITING_HUMAN',
                           AgentThread.id.in_(_approval_scope(actor))])
        if 'approver' not in actor.roles:
            conditions.append(AgentThread.id.is_(None))
    if scene:
        conditions.append(AgentThread.scene == scene)
    if status:
        conditions.append(AgentThread.status == status)
    if updated_after:
        conditions.append(AgentThread.updated_at >= updated_after)
    if updated_before:
        conditions.append(AgentThread.updated_at <= updated_before)
    base = select(AgentThread).where(*conditions)
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    threads = (await session.scalars(base.order_by(AgentThread.updated_at.desc(), AgentThread.created_at.desc())
                                     .offset((page - 1) * page_size).limit(page_size))).all()
    return TaskPage(items=[await _project(session, thread, actor) for thread in threads],
                    total=total, page=page, page_size=page_size)


async def get_task(session: AsyncSession, task_id: UUID, actor: CurrentUser) -> TaskSummary:
    thread = await _load_thread(session, task_id, actor)
    return await _project(session, thread, await require_fresh_identity(actor, session=session))


async def handoff_task(session: AsyncSession, task_id: UUID, actor: CurrentUser) -> TaskSummary:
    thread = await _load_thread(session, task_id, actor)
    if thread.scene in {"document", "email", "work_task", "report", "contract"}:
        raise AppException(ErrorCode.INVALID_STATE, "请在对应工作台审阅任务", http_status=422)
    if thread.scene == "meeting":
        raise AppException(ErrorCode.INVALID_STATE, "会议任务请在会议工作台审阅", http_status=422)
    if thread.user_id != actor.user_id and "admin" not in actor.roles:
        raise AppException(ErrorCode.FORBIDDEN, "只有任务发起人或管理员可以转人工", http_status=403)
    if thread.status in {"APPROVED", "REJECTED", "COMPLETED"}:
        raise AppException(ErrorCode.INVALID_STATE, "已完成任务不能转人工", http_status=422)
    item = await ensure_handoff(session, tenant_id=thread.tenant_id, thread_id=thread.id,
                                user_id=thread.user_id, scene=thread.scene,
                                reason_code="TASK_HANDOFF",
                                context={"status": thread.status, "business_id": thread.business_id})
    await thread_repo.update_thread_status(session, thread, ThreadStatus.WAITING_HUMAN.value)
    await session.commit()
    return await _project(session, thread, actor)


async def retry_task(session: AsyncSession, task_id: UUID, actor: CurrentUser) -> TaskSummary:
    thread = await _load_thread(session, task_id, actor)
    if thread.scene in {"document", "email", "work_task", "report", "contract"}:
        raise AppException(ErrorCode.INVALID_STATE, "请在对应工作台使用明确重试键恢复任务", http_status=422)
    if thread.scene == "meeting":
        from .meeting_service import generate_draft
        await generate_draft(session, actor, thread.business_id, retry=True)
        await session.commit()
        return await _project(session, thread, actor)
    if thread.scene != "leave":
        raise AppException(ErrorCode.INVALID_STATE, "当前任务类型不支持服务端重试", http_status=422)
    from .approval_service import validate_safe_retry

    await validate_safe_retry(session, thread, actor)
    try:
        result = await runtime.invoke(thread.id, None)
    except Exception as exc:
        raise AppException(ErrorCode.DEPENDENCY_FAILED, "任务重试尚未完成，请稍后核对", http_status=502) from exc
    pending = extract_interrupt(await runtime.get_state(thread.id))
    next_action = result.get("next_action")
    status = "WAITING_HUMAN" if pending else map_next_action(next_action)
    await thread_repo.update_thread_status(session, thread, status,
                                           current_interrupt_id=pending[0] if pending else None,
                                           error_code=None, error_msg=None)
    await session.commit()
    return await _project(session, thread, await require_fresh_identity(actor, session=session))
