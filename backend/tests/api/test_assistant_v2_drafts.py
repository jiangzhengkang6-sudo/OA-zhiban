"""统一 OA 智能助手第二阶段：草稿保存、复核与确认写入回归。"""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.errors import AppException
from app.models.assistant_draft import AssistantDraft
from app.models.oa_meeting import OAMeeting
from app.models.work_task import WorkTask
from app.schemas.assistant_v2 import (
    DraftCancelRequest,
    DraftConfirmRequest,
    DraftSaveRequest,
)
from app.schemas.assistant_v2 import ReportDraftRequest
from app.schemas.oa_meeting import MeetingCommand, MeetingCreate
from app.schemas.work_task import WorkTaskCommand
from app.services import meeting_management_service, work_task_service
from app.services import assistant_v2_service as service
from app.services.identity_service import utcnow
from tests.oa_support import oa_db, seed


def task_draft(assignee_id: str, **overrides):
    values = {
        "title": "核对项目交付清单",
        "assignee_id": assignee_id,
        "due_at": utcnow() + timedelta(days=1),
        "priority": "normal",
        "sensitive": False,
    }
    values.update(overrides)
    return DraftSaveRequest(draft_type="task", draft=values)


def confirm_request() -> DraftConfirmRequest:
    return DraftConfirmRequest(
        operation_id=uuid4().hex,
        metadata_confirmed=True,
    )


async def test_task_draft_save_confirm_and_replay(oa_db):
    async with oa_db() as db:
        owner = await seed(db, resources=["work_task"], scope="self")
        assignee = await seed(
            db,
            tenant=owner.tenant_id,
            department=owner.depts[0],
            resources=["work_task"],
            scope="self",
        )
        await db.commit()

        saved = await service.save_draft(db, owner, task_draft(assignee.user_id))
        await db.commit()
        assert saved.status == "DRAFT"
        assert saved.result == {}

        request = confirm_request()
        confirmed = await service.confirm_draft(db, owner, saved.id, request)
        await db.commit()
        task_id = confirmed.result["task_id"]
        assert confirmed.status == "CONFIRMED"
        assert task_id.startswith("WT-")

        task_count = await db.scalar(
            select(func.count()).select_from(WorkTask).where(WorkTask.tenant_id == owner.tenant_id)
        )
        assert task_count == 1

        replayed = await service.confirm_draft(db, owner, saved.id, request)
        await db.commit()
        assert replayed.result["task_id"] == task_id
        task_count = await db.scalar(
            select(func.count()).select_from(WorkTask).where(WorkTask.tenant_id == owner.tenant_id)
        )
        assert task_count == 1

        listed = await service.list_saved_drafts(db, owner)
        assert [row.id for row in listed] == [saved.id]
        assert (await service.get_saved_draft(db, owner, saved.id)).result["task_id"] == task_id


async def test_risky_task_requires_backend_risk_acknowledgement(oa_db):
    async with oa_db() as db:
        owner = await seed(db, resources=["work_task"], scope="self")
        assignee = await seed(
            db,
            tenant=owner.tenant_id,
            department=owner.depts[0],
            resources=["work_task"],
            scope="self",
        )
        await db.commit()

        saved = await service.save_draft(
            db,
            owner,
            task_draft(assignee.user_id, priority="high"),
        )
        await db.commit()
        assert saved.warnings == ["高优先级任务确认时需勾选风险确认。"]

        request = confirm_request()
        with pytest.raises(AppException, match="高优先级任务需要二次确认"):
            await service.confirm_draft(db, owner, saved.id, request)
        await db.rollback()

        request.risk_acknowledged = True
        confirmed = await service.confirm_draft(db, owner, saved.id, request)
        await db.commit()
        assert confirmed.status == "CONFIRMED"
        assert confirmed.result["task_id"]


async def test_save_draft_rejects_cross_tenant_assignee(oa_db):
    async with oa_db() as db:
        owner = await seed(db, resources=["work_task"], scope="self")
        outsider = await seed(db, resources=["work_task"], scope="self")
        await db.commit()

        with pytest.raises(AppException, match="不属于当前租户"):
            await service.save_draft(db, owner, task_draft(outsider.user_id))
        await db.rollback()

        draft_count = await db.scalar(
            select(func.count())
            .select_from(AssistantDraft)
            .where(AssistantDraft.tenant_id == owner.tenant_id)
        )
        assert draft_count == 0


async def test_cancel_draft_blocks_later_confirmation(oa_db):
    async with oa_db() as db:
        owner = await seed(db, resources=["work_task"], scope="self")
        assignee = await seed(
            db,
            tenant=owner.tenant_id,
            department=owner.depts[0],
            resources=["work_task"],
            scope="self",
        )
        await db.commit()

        saved = await service.save_draft(db, owner, task_draft(assignee.user_id))
        await db.commit()
        cancelled = await service.cancel_saved_draft(
            db,
            owner,
            saved.id,
            DraftCancelRequest(reason="信息有误"),
        )
        await db.commit()
        assert cancelled.status == "CANCELLED"
        assert cancelled.notes == "信息有误"

        with pytest.raises(AppException, match="当前草稿不可确认"):
            await service.confirm_draft(db, owner, saved.id, confirm_request())


async def test_meeting_draft_confirm_creates_scheduled_meeting(oa_db):
    async with oa_db() as db:
        owner = await seed(
            db,
            resources=["meeting", "notification", "work_task"],
            scope="self",
        )
        attendee = await seed(
            db,
            tenant=owner.tenant_id,
            resources=["meeting", "notification"],
            scope="self",
        )
        await db.commit()

        starts_at = utcnow() + timedelta(days=1)
        saved = await service.save_draft(
            db,
            owner,
            DraftSaveRequest(
                draft_type="meeting",
                draft={
                    "title": "项目周例会",
                    "agenda": "确认本周风险与下周计划",
                    "starts_at": starts_at,
                    "ends_at": starts_at + timedelta(hours=1),
                    "host_id": owner.user_id,
                    "recorder_id": owner.user_id,
                    "attendee_ids": [attendee.user_id],
                    "location": "第一会议室",
                    "online_url": "",
                    "video_enabled": False,
                },
            ),
        )
        await db.commit()

        confirmed = await service.confirm_draft(db, owner, saved.id, confirm_request())
        await db.commit()
        meeting_id = confirmed.result["meeting_id"]
        assert confirmed.result["state"] == "SCHEDULED"

        meeting = await db.get(OAMeeting, meeting_id)
        assert meeting.state == "SCHEDULED"
        assert meeting.organizer_id == owner.user_id


async def test_task_options_return_only_users_with_task_access(oa_db):
    async with oa_db() as db:
        owner = await seed(db, resources=["work_task"], scope="self")
        eligible = await seed(
            db,
            tenant=owner.tenant_id,
            department=owner.depts[0],
            resources=["work_task"],
            scope="self",
        )
        await seed(
            db,
            tenant=owner.tenant_id,
            department=owner.depts[0],
            scope="self",
        )
        await db.commit()

        result = await service.options(db, owner, "task")
        assert {row["id"] for row in result["users"]} == {
            owner.user_id,
            eligible.user_id,
        }


async def test_monthly_report_draft(oa_db):
    async with oa_db() as db:
        owner = await seed(db, resources=["work_task", "meeting"], scope="self")
        await db.commit()

        result = await service.create_report_draft(
            db,
            owner,
            ReportDraftRequest(report_type="monthly", date="2026-11-10"),
        )
        assert result.report_type == "monthly"
        assert result.title == "2026年11月工作月报"
        assert result.period_start.year == 2026
        assert result.period_start.month == 11
        assert result.markdown.startswith("# 2026年11月工作月报")


async def test_task_complete_action_draft(oa_db):
    async with oa_db() as db:
        owner = await seed(db, resources=["work_task"], scope="self")
        await db.commit()

        created_draft = await service.save_draft(
            db, owner, task_draft(owner.user_id)
        )
        await db.commit()
        created = await service.confirm_draft(
            db, owner, created_draft.id, confirm_request()
        )
        await db.commit()
        task_id = created.result["task_id"]
        task = await work_task_service.get_task(db, owner, task_id)
        started = await work_task_service.task_command(
            db,
            owner,
            task_id,
            WorkTaskCommand(
                idempotency_key=uuid4().hex,
                expected_version=task.version,
                action="start",
            ),
        )
        await db.commit()

        action_draft = await service.save_draft(
            db,
            owner,
            DraftSaveRequest(
                draft_type="task",
                draft={
                    "operation": "complete",
                    "task_id": task_id,
                    "expected_version": started.version,
                    "comment": "已完成核对",
                },
            ),
        )
        await db.commit()
        confirmed = await service.confirm_draft(
            db, owner, action_draft.id, confirm_request()
        )
        await db.commit()
        assert confirmed.result == {
            "task_id": task_id,
            "state": "COMPLETED",
        }
        completed = await work_task_service.get_task(db, owner, task_id)
        assert completed.status == "COMPLETED"
        assert completed.progress == 100


async def test_meeting_cancel_action_draft(oa_db):
    async with oa_db() as db:
        owner = await seed(
            db,
            resources=["meeting", "notification"],
            scope="self",
        )
        attendee = await seed(
            db,
            tenant=owner.tenant_id,
            resources=["meeting", "notification"],
            scope="self",
        )
        await db.commit()

        starts_at = utcnow() + timedelta(days=1)
        saved_meeting = await meeting_management_service.save(
            db,
            owner,
            MeetingCreate(
                operation_id=uuid4().hex,
                title="项目复盘会",
                agenda="复盘风险",
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=1),
                host_id=owner.user_id,
                recorder_id=owner.user_id,
                attendee_ids=[attendee.user_id],
                location="第一会议室",
            ),
        )
        meeting_id = saved_meeting.result["id"]
        revision = saved_meeting.result["revision"]
        await meeting_management_service.transition(
            db,
            owner,
            meeting_id,
            MeetingCommand(
                operation_id=uuid4().hex,
                expected_revision=revision,
            ),
            "publish",
        )
        await db.commit()

        action_draft = await service.save_draft(
            db,
            owner,
            DraftSaveRequest(
                draft_type="meeting",
                draft={
                    "operation": "cancel",
                    "meeting_id": meeting_id,
                    "expected_revision": revision + 1,
                    "reason": "会议时间冲突",
                },
            ),
        )
        await db.commit()
        confirmed = await service.confirm_draft(
            db, owner, action_draft.id, confirm_request()
        )
        await db.commit()
        assert confirmed.result == {
            "meeting_id": meeting_id,
            "state": "CANCELLED",
        }
        assert (await db.get(OAMeeting, meeting_id)).state == "CANCELLED"
