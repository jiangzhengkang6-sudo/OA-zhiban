"""统一助手周期任务规则回归测试。"""

from datetime import timedelta
from uuid import uuid4

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

