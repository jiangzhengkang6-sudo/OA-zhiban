"""
OA 智能体管理系统 - 审计数据访问层。

提供审计事件的写入与条件检索。写入仅存摘要（调用方负责脱敏），检索支持按
trace_id / thread_id / business_id / actor / action / 时间范围过滤与分页。
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.audit_event import AuditEvent
from ..models.meeting_record import MeetingRecord
from ..models.document_record import DocumentRecord
from ..models.email_record import EmailRecord
from ..models.report_record import ReportRecord
from ..models.contract_record import ContractRecord
from ..models.work_task_batch import WorkTaskBatch
from ..models.work_task import WorkTask


async def add_event(
    session: AsyncSession,
    *,
    trace_id: Optional[str],
    action: str,
    thread_id: Optional[UUID] = None,
    business_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    input_summary: Optional[dict] = None,
    output_summary: Optional[dict] = None,
    result: Optional[str] = None,
    error_code: Optional[str] = None,
    policy_version: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> AuditEvent:
    """写入一条审计事件。

    Args:
        session: 数据库会话。
        trace_id: 追踪 ID。
        action: 事件动作。
        thread_id: 会话 ID。
        business_id: 业务单据号。
        actor_id: 操作者。
        target_type: 目标类型。
        target_id: 目标 ID。
        tool_name: 工具名。
        input_summary: 输入摘要。
        output_summary: 输出摘要。
        result: 结果。
        error_code: 错误码。
        policy_version: 策略版本。
        duration_ms: 耗时。

    Returns:
        AuditEvent: 写入的事件记录。
    """
    event = AuditEvent(
        trace_id=trace_id, action=action, thread_id=thread_id,
        business_id=business_id, actor_id=actor_id, target_type=target_type,
        target_id=target_id, tool_name=tool_name, input_summary=input_summary,
        output_summary=output_summary, result=result, error_code=error_code,
        policy_version=policy_version, duration_ms=duration_ms,
    )
    session.add(event)
    await session.flush()
    return event


async def query_events(
    session: AsyncSession,
    *,
    trace_id: Optional[str] = None,
    thread_id: Optional[UUID] = None,
    business_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    action: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 20,
    meeting_tenant_id: Optional[str] = None,
) -> tuple[list[AuditEvent], int]:
    """按条件检索审计事件（分页）。

    Args:
        session: 数据库会话。
        trace_id: 追踪 ID。
        thread_id: 会话 ID。
        business_id: 业务单据号。
        actor_id: 操作者。
        action: 事件动作。
        start_time: 起始时间。
        end_time: 结束时间。
        page: 页码。
        page_size: 每页条数。

    Returns:
        tuple[list[AuditEvent], int]: (当前页事件列表, 总条数)。
    """
    conditions = []
    if meeting_tenant_id is not None:
        for kind, record_type, id_column in [("document", DocumentRecord, DocumentRecord.document_id),
                                             ("email", EmailRecord, EmailRecord.email_id),
                                             ("report", ReportRecord, ReportRecord.report_id),
                                             ("contract", ContractRecord, ContractRecord.contract_id)]:
            event = or_(AuditEvent.target_type == kind, AuditEvent.action.startswith(kind + "_"))
            visible = select(record_type.id).where(record_type.tenant_id == meeting_tenant_id,
                record_type.thread_id == AuditEvent.thread_id, id_column == AuditEvent.business_id).exists()
            conditions.append(or_(and_(AuditEvent.target_type.is_distinct_from(kind),
                ~AuditEvent.action.startswith(kind + "_")), and_(event, visible)))
        work_event = or_(AuditEvent.target_type.in_(['work_task', 'work_task_batch']),
            AuditEvent.action.startswith('work_task_'))
        visible_batch = select(WorkTaskBatch.id).where(WorkTaskBatch.tenant_id == meeting_tenant_id,
            WorkTaskBatch.thread_id == AuditEvent.thread_id, WorkTaskBatch.batch_id == AuditEvent.business_id).exists()
        visible_task = select(WorkTask.id).where(WorkTask.tenant_id == meeting_tenant_id,
            WorkTask.task_id == AuditEvent.business_id,
            WorkTask.task_id == AuditEvent.target_id).exists()
        other_event = and_(AuditEvent.target_type.is_distinct_from('work_task'),
            AuditEvent.target_type.is_distinct_from('work_task_batch'), ~AuditEvent.action.startswith('work_task_'))
        conditions.append(or_(other_event, and_(work_event, or_(visible_batch, visible_task))))
        meeting_event = or_(AuditEvent.target_type == "meeting", AuditEvent.action.startswith("meeting_"))
        visible_meeting = select(MeetingRecord.id).where(
            MeetingRecord.tenant_id == meeting_tenant_id,
            MeetingRecord.thread_id == AuditEvent.thread_id,
            MeetingRecord.meeting_id == AuditEvent.business_id,
        ).exists()
        conditions.append(or_(and_(AuditEvent.target_type.is_distinct_from("meeting"),
                                   ~AuditEvent.action.startswith("meeting_")),
                              and_(meeting_event, visible_meeting)))
    if trace_id:
        conditions.append(AuditEvent.trace_id == trace_id)
    if thread_id:
        conditions.append(AuditEvent.thread_id == thread_id)
    if business_id:
        conditions.append(AuditEvent.business_id == business_id)
    if actor_id:
        conditions.append(AuditEvent.actor_id == actor_id)
    if action:
        conditions.append(AuditEvent.action == action)
    if start_time:
        conditions.append(AuditEvent.created_at >= start_time)
    if end_time:
        conditions.append(AuditEvent.created_at <= end_time)

    count_stmt = select(func.count()).select_from(AuditEvent).where(*conditions)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = (
        select(AuditEvent)
        .where(*conditions)
        .order_by(AuditEvent.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total
