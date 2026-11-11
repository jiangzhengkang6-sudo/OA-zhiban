"""统一助手周期任务规则与到期调度服务。"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..models.agent_thread import AgentThread
from ..models.assistant_draft import AssistantDraft
from ..models.assistant_schedule import AssistantSchedule
from ..models.identity import OAUser
from ..models.work_task import WorkTask
from ..models.work_task_batch import WorkTaskBatch
from ..models.work_task_event import WorkTaskEvent
from ..models.work_task_notification import WorkTaskNotification
from ..schemas.assistant_v2 import (
    AssistantSchedulePayload,
    AssistantScheduleResponse,
)
from . import audit_service
from .authorization_service import require_permission
from .identity_service import current_identity, lock_tenant

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
MAX_HORIZON_DAYS = 366
REMINDER_WINDOW = timedelta(minutes=30)


def now_shanghai() -> datetime:
    return datetime.now(SHANGHAI_TZ)


def validate_schedule_payload(
    raw: dict[str, Any],
) -> tuple[AssistantSchedulePayload, list[str]]:
    """强类型校验周期规则，并把规则限制在安全边界内。"""

    payload = AssistantSchedulePayload.model_validate(raw)
    now = now_shanghai()
    start = payload.starts_at.astimezone(SHANGHAI_TZ) if payload.starts_at else now

    if payload.frequency == "daily":
        if payload.day_of_week is not None or payload.day_of_month is not None:
            raise AppException(ErrorCode.BAD_REQUEST, "每日规则不能设置星期或日期。", http_status=422)
    elif payload.frequency == "weekly":
        if payload.day_of_week is None or payload.day_of_month is not None:
            raise AppException(ErrorCode.BAD_REQUEST, "每周规则必须仅设置星期。", http_status=422)
    elif payload.day_of_month is None or payload.day_of_week is not None:
        raise AppException(ErrorCode.BAD_REQUEST, "每月规则必须仅设置日期。", http_status=422)

    if start < now - timedelta(minutes=1):
        raise AppException(ErrorCode.BAD_REQUEST, "周期规则开始时间不能早于当前时间。", http_status=422)
    if payload.ends_at is None and payload.max_occurrences is None:
        raise AppException(
            ErrorCode.BAD_REQUEST,
            "周期规则必须设置结束日期或最大执行次数。",
            http_status=422,
        )
    if payload.ends_at is not None:
        ends_at = payload.ends_at.astimezone(SHANGHAI_TZ)
        if ends_at <= start:
            raise AppException(ErrorCode.BAD_REQUEST, "结束时间必须晚于开始时间。", http_status=422)
        if ends_at > start + timedelta(days=MAX_HORIZON_DAYS):
            raise AppException(
                ErrorCode.BAD_REQUEST,
                f"周期规则最长不得超过 {MAX_HORIZON_DAYS} 天。",
                http_status=422,
            )

    first_run = calculate_next_run(payload, start - timedelta(seconds=1))
    if first_run is None:
        raise AppException(ErrorCode.BAD_REQUEST, "结束条件前没有可执行时间。", http_status=422)
    return payload, []


def _add_month(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def calculate_next_run(
    payload: AssistantSchedulePayload,
    after: datetime,
    *,
    inclusive: bool = False,
) -> datetime | None:
    """按上海时区计算晚于（或包含）after 的下一次执行时间。"""

    after = after.astimezone(SHANGHAI_TZ)
    run_time = payload.run_time
    if payload.frequency == "daily":
        day = after.date()
        candidate = datetime.combine(day, run_time, SHANGHAI_TZ)
        if candidate < after or (candidate == after and not inclusive):
            candidate = datetime.combine(day + timedelta(days=1), run_time, SHANGHAI_TZ)
    elif payload.frequency == "weekly":
        day = after.date()
        delta = (payload.day_of_week - day.weekday()) % 7
        candidate_day = day + timedelta(days=delta)
        candidate = datetime.combine(candidate_day, run_time, SHANGHAI_TZ)
        if candidate < after or (candidate == after and not inclusive):
            candidate = datetime.combine(candidate_day + timedelta(days=7), run_time, SHANGHAI_TZ)
    else:
        candidate = datetime(
            after.year,
            after.month,
            payload.day_of_month,
            run_time.hour,
            run_time.minute,
            run_time.second,
            tzinfo=SHANGHAI_TZ,
        )
        if candidate < after or (candidate == after and not inclusive):
            candidate = _add_month(candidate)

    if payload.starts_at and candidate < payload.starts_at.astimezone(SHANGHAI_TZ):
        return calculate_next_run(payload, payload.starts_at - timedelta(seconds=1))
    if payload.ends_at and candidate > payload.ends_at.astimezone(SHANGHAI_TZ):
        return None
    return candidate


async def create_schedule(session, actor, draft: AssistantDraft) -> dict[str, Any]:
    """确认周期草稿后创建规则，本步骤仍不创建任何业务任务。"""

    payload, _ = validate_schedule_payload(draft.payload)
    start = payload.starts_at.astimezone(SHANGHAI_TZ) if payload.starts_at else now_shanghai()
    first_run = calculate_next_run(payload, start - timedelta(seconds=1))
    schedule = AssistantSchedule(
        id=str(uuid4()),
        tenant_id=actor.tenant_id,
        owner_id=actor.user_id,
        status="ACTIVE",
        title=payload.title,
        frequency=payload.frequency,
        day_of_week=payload.day_of_week,
        day_of_month=payload.day_of_month,
        run_time=payload.run_time,
        next_run_at=first_run,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        max_occurrences=payload.max_occurrences,
        occurrence_count=0,
        template={
            "title": payload.title,
            "priority": payload.priority,
            "sensitive": False,
            "source_draft_id": draft.id,
        },
    )
    session.add(schedule)
    await session.flush()
    draft.result = {
        "schedule_id": schedule.id,
        "next_run_at": schedule.next_run_at.isoformat(),
    }
    await audit_service.audit(
        session,
        "assistant_schedule_created",
        actor_id=actor.user_id,
        target_type="assistant_schedule",
        target_id=schedule.id,
        input_summary={"frequency": schedule.frequency},
    )
    return draft.result


def _schedule_response(row: AssistantSchedule) -> AssistantScheduleResponse:
    return AssistantScheduleResponse(
        id=row.id,
        status=row.status,
        title=row.title,
        frequency=row.frequency,
        day_of_week=row.day_of_week,
        day_of_month=row.day_of_month,
        run_time=row.run_time,
        next_run_at=row.next_run_at,
        last_run_at=row.last_run_at,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        max_occurrences=row.max_occurrences,
        occurrence_count=row.occurrence_count,
        template=row.template,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def list_schedules(session, actor) -> list[AssistantScheduleResponse]:
    rows = (
        await session.scalars(
            select(AssistantSchedule)
            .where(
                AssistantSchedule.tenant_id == actor.tenant_id,
                AssistantSchedule.owner_id == actor.user_id,
            )
            .order_by(AssistantSchedule.updated_at.desc())
            .limit(100)
        )
    ).all()
    return [_schedule_response(row) for row in rows]


async def cancel_schedule(
    session,
    actor,
    schedule_id: str,
    reason: str,
) -> AssistantScheduleResponse:
    await lock_tenant(session, actor.tenant_id)
    row = await _owned_schedule(session, actor, schedule_id, lock=True)
    if row.status == "CANCELLED":
        return _schedule_response(row)
    if row.status not in {"ACTIVE", "PAUSED"}:
        raise AppException(ErrorCode.INVALID_STATE, "当前规则状态不可取消。", http_status=422)
    row.status = "CANCELLED"
    row.next_run_at = None
    await session.flush()
    await audit_service.audit(
        session,
        "assistant_schedule_cancelled",
        actor_id=actor.user_id,
        target_type="assistant_schedule",
        target_id=row.id,
        output_summary={"reason": reason},
    )
    return _schedule_response(row)


async def _owned_schedule(session, actor, schedule_id: str, *, lock: bool = False):
    query = select(AssistantSchedule).where(
        AssistantSchedule.tenant_id == actor.tenant_id,
        AssistantSchedule.id == schedule_id,
        AssistantSchedule.owner_id == actor.user_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(query)
    if row is None:
        raise AppException(ErrorCode.NOT_FOUND, "周期规则不存在或不可访问。", http_status=404)
    return row


async def _pause_schedule(session, schedule: AssistantSchedule, reason: str) -> None:
    schedule.status = "PAUSED"
    schedule.next_run_at = None
    await session.flush()
    await audit_service.audit(
        session,
        "assistant_schedule_paused",
        actor_id=schedule.owner_id,
        target_type="assistant_schedule",
        target_id=schedule.id,
        output_summary={"reason": reason[:500]},
    )


async def scan_due_schedules(session) -> dict[str, int]:
    """扫描到期规则；单条规则失败只暂停该规则，不影响其他规则。"""

    now = now_shanghai()
    candidates = (
        await session.scalars(
            select(AssistantSchedule.id)
            .where(
                AssistantSchedule.status == "ACTIVE",
                AssistantSchedule.next_run_at <= now,
            )
            .order_by(AssistantSchedule.next_run_at)
            .limit(20)
        )
    ).all()

    created = paused = 0
    for schedule_id in candidates:
        savepoint = await session.begin_nested()
        try:
            schedule = await session.get(
                AssistantSchedule,
                schedule_id,
                with_for_update=True,
                populate_existing=True,
            )
            if schedule is None or schedule.status != "ACTIVE" or schedule.next_run_at is None:
                await savepoint.rollback()
                continue
            await lock_tenant(session, schedule.tenant_id)
            user = await session.get(OAUser, schedule.owner_id)
            if user is None or user.tenant_id != schedule.tenant_id or user.status != "active":
                await _pause_schedule(schedule, "负责人账号不存在、已停用或租户不匹配。")
                paused += 1
            else:
                owner = await current_identity(session, user)
                require_permission(owner, "work_task", "read")
                require_permission(owner, "work_task", "write")
                if await _create_occurrence(session, owner, schedule):
                    created += 1
        except AppException as exc:
            await savepoint.rollback()
            # 回滚后需重新锁定规则并记录暂停原因。
            schedule = await session.get(AssistantSchedule, schedule_id, with_for_update=True)
            if schedule and schedule.status == "ACTIVE":
                nested = await session.begin_nested()
                try:
                    await lock_tenant(session, schedule.tenant_id)
                    await _pause_schedule(schedule, f"周期规则安全校验未通过：{exc.message}")
                    paused += 1
                except Exception:
                    await nested.rollback()
        except Exception:
            await savepoint.rollback()
            raise
    await session.flush()
    return {"created": created, "paused": paused}


async def _create_occurrence(session, owner, schedule: AssistantSchedule) -> bool:
    occurrence_at = schedule.next_run_at.astimezone(SHANGHAI_TZ)
    occurrence_key = occurrence_at.strftime("occ-%Y%m%d-%H%M")
    occurrence_idempotency_key = f"schedule:{schedule.id}:{occurrence_key}"
    existing = await session.scalar(
        select(WorkTaskBatch.id).where(
            WorkTaskBatch.tenant_id == schedule.tenant_id,
            WorkTaskBatch.idempotency_key == occurrence_idempotency_key,
        )
    )
    if existing is not None:
        await _advance_schedule(schedule, occurrence_at)
        return False

    source_ref = f"schedule:{schedule.id}:{occurrence_key}"
    snapshot = {
        "ref": source_ref,
        "source_type": "schedule",
        "source_id": schedule.id,
        "version": occurrence_key,
        "title": schedule.title,
        "content": schedule.title,
        "action_items": [],
    }
    thread = AgentThread(
        tenant_id=owner.tenant_id,
        user_id=owner.user_id,
        scene="oa_schedule",
        intent="create_task",
        status="CONFIRMED",
    )
    session.add(thread)
    await session.flush()

    batch = WorkTaskBatch(
        batch_id="WTS-" + uuid4().hex[:12].upper(),
        thread_id=thread.id,
        tenant_id=owner.tenant_id,
        owner_id=owner.user_id,
        source_type="schedule",
        source_id=schedule.id,
        source_version=occurrence_key,
        source_snapshot=snapshot,
        idempotency_key=occurrence_idempotency_key,
    )
    session.add(batch)
    await session.flush()

    task = WorkTask(
        id=uuid4(),
        task_id="WT-" + uuid4().hex[:12].upper(),
        batch_id=batch.id,
        tenant_id=owner.tenant_id,
        creator_id=owner.user_id,
        assignee_id=owner.user_id,
        source_type="schedule",
        source_id=schedule.id,
        source_version=occurrence_key,
        candidate_id=schedule.id,
        source_refs=[source_ref],
        title=schedule.template.get("title", schedule.title),
        priority=schedule.template.get("priority", "normal"),
        sensitive=False,
        due_at=occurrence_at + REMINDER_WINDOW,
        status="OPEN",
        progress=0,
        version=1,
        deadline_version=1,
        notification_scan_at=occurrence_at,
    )
    session.add(task)
    await session.flush()
    session.add(
        WorkTaskEvent(
            task_id=task.id,
            actor_id=owner.user_id,
            action="created",
            version=1,
            details={"schedule_id": schedule.id, "occurrence": occurrence_key},
        )
    )
    session.add(
        WorkTaskNotification(
            id=uuid4(),
            task_id=task.id,
            tenant_id=owner.tenant_id,
            deadline_version=1,
            stage="schedule",
            recipient_id=owner.user_id,
        )
    )
    schedule.occurrence_count += 1
    schedule.last_run_at = occurrence_at
    await _advance_schedule(schedule, occurrence_at)
    thread.business_id = task.task_id
    await audit_service.audit(
        session,
        "assistant_schedule_task_created",
        thread_id=thread.id,
        business_id=task.task_id,
        actor_id=owner.user_id,
        target_type="work_task",
        target_id=task.task_id,
        input_summary={"occurrence": occurrence_key},
    )
    return True


async def _advance_schedule(
    schedule: AssistantSchedule,
    occurrence_at: datetime,
) -> None:
    if schedule.max_occurrences is not None and schedule.occurrence_count >= schedule.max_occurrences:
        schedule.status = "COMPLETED"
        schedule.next_run_at = None
        return

    payload = AssistantSchedulePayload(
        title=schedule.title,
        frequency=schedule.frequency,
        day_of_week=schedule.day_of_week,
        day_of_month=schedule.day_of_month,
        run_time=schedule.run_time,
        starts_at=schedule.starts_at,
        ends_at=schedule.ends_at,
        max_occurrences=schedule.max_occurrences,
        priority=schedule.template.get("priority", "normal"),
        sensitive=False,
    )
    next_run = calculate_next_run(payload, occurrence_at)
    if next_run is None:
        schedule.status = "COMPLETED"
        schedule.next_run_at = None
    else:
        schedule.next_run_at = next_run

