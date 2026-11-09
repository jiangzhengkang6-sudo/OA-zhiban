"""Unique private overdue notifications under current permissions and row locks."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import select, update, and_, or_, exists
from sqlalchemy.dialects.postgresql import insert
from ..core.context import CurrentUser
from ..core.errors import AppException
from ..models.work_task import WorkTask
from ..models.work_task_batch import WorkTaskBatch
from ..models.work_task_notification import WorkTaskNotification
from . import work_task_service as service
from .identity_service import lock_tenant


async def scan_overdue(session, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Scheduler requires timezone-aware time")
    inserted = 0
    pending = or_(~_notified("overdue", WorkTask.assignee_id), and_(WorkTask.due_at <= now - timedelta(hours=24),
        ~_notified("escalated", WorkTask.creator_id)))
    query = select(WorkTask).where(WorkTask.status.in_(["OPEN", "IN_PROGRESS"]),
        WorkTask.due_at < now, pending).order_by(WorkTask.notification_scan_at.asc().nulls_first(),
        WorkTask.due_at, WorkTask.id).limit(200)
    candidates = (await session.execute(query.with_only_columns(WorkTask.id, WorkTask.tenant_id))).all()
    # Share organization/task command lock order before locking any task rows.
    for tenant in sorted({row.tenant_id for row in candidates}):
        await lock_tenant(session, tenant)
    tasks = (await session.scalars(query.where(WorkTask.id.in_([row.id for row in candidates]))
        .with_for_update(skip_locked=True).execution_options(populate_existing=True))).all()
    for task in tasks:
        inserted += await _notify_task(session, task, now)
        # Preserve business modification time while rotating even unavailable sources.
        await session.execute(update(WorkTask).where(WorkTask.id == task.id)
            .values(notification_scan_at=now, updated_at=task.updated_at))
    await session.flush()
    return inserted


def _notified(stage, recipient):
    return exists(select(WorkTaskNotification.id).where(WorkTaskNotification.task_id == WorkTask.id,
        WorkTaskNotification.deadline_version == WorkTask.deadline_version,
        WorkTaskNotification.stage == stage, WorkTaskNotification.recipient_id == recipient))


async def _notify_task(session, task, now):
    inserted = 0
    batch = await session.get(WorkTaskBatch, task.batch_id)
    recipients = [("overdue", task.assignee_id)]
    if now >= task.due_at + timedelta(hours=24):
        recipients.append(("escalated", task.creator_id))
    for stage, user_id in recipients:
        try:
            actor = await service._identity(session, CurrentUser(user_id=user_id, tenant_id=task.tenant_id))
            await service._notification_access(session, actor, task)
            await service._available(session, actor, batch)
            if not (task.handoff_department_id and user_id == task.assignee_id):
                creator = await service._identity(session, CurrentUser(user_id=task.creator_id, tenant_id=task.tenant_id))
                await service._source_access(session, creator, batch)
        except AppException:
            continue
        row_id = await session.scalar(insert(WorkTaskNotification).values(id=uuid4(), task_id=task.id,
            tenant_id=task.tenant_id, deadline_version=task.deadline_version, stage=stage, recipient_id=user_id)
            .on_conflict_do_nothing(constraint="uq_work_task_notification_stage").returning(WorkTaskNotification.id))
        inserted += row_id is not None
    return inserted
