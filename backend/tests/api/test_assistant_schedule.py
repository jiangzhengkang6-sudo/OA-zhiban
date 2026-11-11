"""统一助手周期任务规则回归测试。"""

from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.errors import AppException
from sqlalchemy import func, select, update

from app.models.assistant_schedule import AssistantSchedule
from app.models.work_task import WorkTask
from app.models.work_task_notification import WorkTaskNotification
from app.schemas.assistant_v2 import (
    DraftConfirmRequest,
    DraftParseRequest,
    DraftSaveRequest,
)
from app.services import assistant_v2_service as service
from app.services.assistant_schedule_service import now_shanghai
from tests.oa_support import oa_db, seed


def confirm_request() -> DraftConfirmRequest:
    return DraftConfirmRequest(
        operation_id=uuid4().hex,
        metadata_confirmed=True,
    )


async def test_daily_schedule_parse_confirm_and_due_once(oa_db):
    async with oa_db() as db:
        await db.execute(
            update(AssistantSchedule)
            .where(AssistantSchedule.status.in_(["ACTIVE", "PAUSED"]))
            .values(status="CANCELLED", next_run_at=None)
        )
        owner = await seed(db, resources=["work_task"], scope="self")
        await db.commit()

        parsed = await service.parse_natural_draft(
            db,
            owner,
            DraftParseRequest(text="每天上午9点提醒我检查工单，共2次"),
        )
        assert parsed.draft_type == "schedule"
        assert parsed.missing_required == []
        assert parsed.draft["frequency"] == "daily"
        assert parsed.draft["max_occurrences"] == 2

        saved = await service.save_draft(
            db,
            owner,
            DraftSaveRequest(draft_type="schedule", draft=parsed.draft),
        )
        await db.commit()
        confirmed = await service.confirm_draft(db, owner, saved.id, confirm_request())
        await db.commit()

        schedule = await db.scalar(
            select(AssistantSchedule).where(AssistantSchedule.owner_id == owner.user_id)
        )
        assert schedule is not None
        assert schedule.id == confirmed.result["schedule_id"]
        assert schedule.status == "ACTIVE"
        assert schedule.occurrence_count == 0

        occurrence_at = now_shanghai() - timedelta(minutes=5)
        schedule.next_run_at = occurrence_at
        await db.commit()

        report = await service.assistant_schedule_service.scan_due_schedules(db)
        await db.commit()
        assert report == {"created": 1, "paused": 0}

        task_count = await db.scalar(
            select(func.count()).select_from(WorkTask).where(
                WorkTask.tenant_id == owner.tenant_id,
                WorkTask.source_type == "schedule",
            )
        )
        notice_count = await db.scalar(
            select(func.count()).select_from(WorkTaskNotification).where(
                WorkTaskNotification.tenant_id == owner.tenant_id,
                WorkTaskNotification.stage == "schedule",
            )
        )
        assert task_count == notice_count == 1

        await db.refresh(schedule)
        assert schedule.occurrence_count == 1
        assert schedule.last_run_at is not None

        # 同一执行时间被重复扫描时，只推进规则，不重复生成任务。
        schedule.next_run_at = schedule.last_run_at
        await db.commit()
        report = await service.assistant_schedule_service.scan_due_schedules(db)
        await db.commit()
        assert report == {"created": 0, "paused": 0}
        task_count = await db.scalar(
            select(func.count()).select_from(WorkTask).where(
                WorkTask.tenant_id == owner.tenant_id,
                WorkTask.source_type == "schedule",
            )
        )
        assert task_count == 1


async def test_schedule_cancel_prevents_execution(oa_db):
    async with oa_db() as db:
        await db.execute(
            update(AssistantSchedule)
            .where(AssistantSchedule.status.in_(["ACTIVE", "PAUSED"]))
            .values(status="CANCELLED", next_run_at=None)
        )
        owner = await seed(db, resources=["work_task"], scope="self")
        await db.commit()

        parsed = await service.parse_natural_draft(
            db,
            owner,
            DraftParseRequest(text="每周五下午6点提醒我整理周报，持续4周"),
        )
        saved = await service.save_draft(
            db,
            owner,
            DraftSaveRequest(draft_type="schedule", draft=parsed.draft),
        )
        confirmed = await service.confirm_draft(db, owner, saved.id, confirm_request())
        await db.commit()

        cancelled = await service.cancel_schedule_rule(
            db,
            owner,
            confirmed.result["schedule_id"],
            "规则调整",
        )
        await db.commit()
        assert cancelled.status == "CANCELLED"
        assert cancelled.next_run_at is None

        report = await service.assistant_schedule_service.scan_due_schedules(db)
        await db.commit()
        assert report == {"created": 0, "paused": 0}
        task_count = await db.scalar(
            select(func.count()).select_from(WorkTask).where(
                WorkTask.tenant_id == owner.tenant_id
            )
        )
        assert task_count == 0


async def _create_confirmed_schedule(db, owner, text):
    parsed = await service.parse_natural_draft(
        db,
        owner,
        DraftParseRequest(text=text),
    )
    saved = await service.save_draft(
        db,
        owner,
        DraftSaveRequest(draft_type="schedule", draft=parsed.draft),
    )
    confirmed = await service.confirm_draft(db, owner, saved.id, confirm_request())
    await db.commit()
    return await db.scalar(
        select(AssistantSchedule).where(
            AssistantSchedule.id == confirmed.result["schedule_id"]
        )
    )


def schedule_edit(schedule_id: str, **overrides) -> DraftSaveRequest:
    values = {
        "title": "整理月报",
        "schedule_id": schedule_id,
        "frequency": "weekly",
        "day_of_week": 4,
        "day_of_month": None,
        "run_time": "18:00:00+08:00",
        "starts_at": None,
        "ends_at": None,
        "max_occurrences": 4,
        "priority": "normal",
        "sensitive": False,
    }
    values.update(overrides)
    return DraftSaveRequest(draft_type="schedule", draft=values)


async def test_paused_schedule_resume(oa_db):
    async with oa_db() as db:
        await db.execute(
            update(AssistantSchedule)
            .where(AssistantSchedule.status.in_(["ACTIVE", "PAUSED"]))
            .values(status="CANCELLED", next_run_at=None)
        )
        owner = await seed(db, resources=["work_task"], scope="self")
        await db.commit()

        schedule = await _create_confirmed_schedule(
            db, owner, "每天上午9点提醒我检查工单，共2次"
        )
        schedule.status = "PAUSED"
        schedule.next_run_at = None
        schedule.pause_reason = "周期规则安全校验未通过：权限变化"
        await db.commit()

        resumed = await service.resume_schedule_rule(
            db, owner, schedule.id, "权限已恢复"
        )
        await db.commit()

        assert resumed.status == "ACTIVE"
        assert resumed.pause_reason is None
        assert resumed.next_run_at is not None
        assert resumed.next_run_at >= now_shanghai() - timedelta(minutes=1)


async def test_resume_rejected_after_end(oa_db):
    async with oa_db() as db:
        await db.execute(
            update(AssistantSchedule)
            .where(AssistantSchedule.status.in_(["ACTIVE", "PAUSED"]))
            .values(status="CANCELLED", next_run_at=None)
        )
        owner = await seed(db, resources=["work_task"], scope="self")
        await db.commit()

        schedule = await _create_confirmed_schedule(
            db, owner, "每周五下午6点提醒我整理周报，持续4周"
        )
        schedule.status = "PAUSED"
        schedule.next_run_at = None
        schedule.ends_at = now_shanghai() - timedelta(days=1)
        await db.commit()

        with pytest.raises(AppException) as exc_info:
            await service.resume_schedule_rule(db, owner, schedule.id)
        assert exc_info.value.http_status == 422


async def test_update_active_schedule(oa_db):
    async with oa_db() as db:
        await db.execute(
            update(AssistantSchedule)
            .where(AssistantSchedule.status.in_(["ACTIVE", "PAUSED"]))
            .values(status="CANCELLED", next_run_at=None)
        )
        owner = await seed(db, resources=["work_task"], scope="self")
        await db.commit()

        schedule = await _create_confirmed_schedule(
            db, owner, "每天上午9点提醒我检查工单，共2次"
        )

        saved = await service.save_draft(
            db, owner, schedule_edit(schedule.id, title="整理部门周报")
        )
        confirmed = await service.confirm_draft(db, owner, saved.id, confirm_request())
        await db.commit()

        assert confirmed.result["updated"] is True
        await db.refresh(schedule)
        assert schedule.title == "整理部门周报"
        assert schedule.frequency == "weekly"
        assert schedule.day_of_week == 4
        assert schedule.run_time.isoformat().startswith("18:00")
        assert schedule.max_occurrences == 4
        assert schedule.status == "ACTIVE"
        assert schedule.next_run_at is not None


async def test_update_paused_schedule_keeps_paused(oa_db):
    async with oa_db() as db:
        await db.execute(
            update(AssistantSchedule)
            .where(AssistantSchedule.status.in_(["ACTIVE", "PAUSED"]))
            .values(status="CANCELLED", next_run_at=None)
        )
        owner = await seed(db, resources=["work_task"], scope="self")
        await db.commit()

        schedule = await _create_confirmed_schedule(
            db, owner, "每周五下午6点提醒我整理周报，持续4周"
        )
        schedule.status = "PAUSED"
        schedule.next_run_at = None
        schedule.pause_reason = "权限变化"
        await db.commit()

        saved = await service.save_draft(db, owner, schedule_edit(schedule.id))
        confirmed = await service.confirm_draft(db, owner, saved.id, confirm_request())
        await db.commit()

        assert confirmed.result["status"] == "PAUSED"
        await db.refresh(schedule)
        assert schedule.status == "PAUSED"
        assert schedule.next_run_at is None

        # 恢复时使用编辑后的频率重新计算。
        resumed = await service.resume_schedule_rule(db, owner, schedule.id)
        await db.commit()
        assert resumed.status == "ACTIVE"
        assert resumed.frequency == "weekly"


async def test_update_rejects_max_occurrences_below_executed(oa_db):
    async with oa_db() as db:
        await db.execute(
            update(AssistantSchedule)
            .where(AssistantSchedule.status.in_(["ACTIVE", "PAUSED"]))
            .values(status="CANCELLED", next_run_at=None)
        )
        owner = await seed(db, resources=["work_task"], scope="self")
        await db.commit()

        schedule = await _create_confirmed_schedule(
            db, owner, "每天上午9点提醒我检查工单，共2次"
        )
        schedule.occurrence_count = 2
        await db.commit()

        saved = await service.save_draft(
            db, owner, schedule_edit(schedule.id, max_occurrences=1)
        )
        with pytest.raises(AppException) as exc_info:
            await service.confirm_draft(db, owner, saved.id, confirm_request())
        assert exc_info.value.http_status == 422

