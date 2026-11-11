"""统一 OA 智能助手 V2 自然语言解析单元测试。"""

from datetime import date

from app.core.context import CurrentUser
from app.services.assistant_v2_service import _NaturalDraftParser


def build_parser() -> _NaturalDraftParser:
    actor = CurrentUser(
        user_id="u-zhang",
        tenant_id="tenant-local",
        roles=["employee"],
        data_scope={"identity_provider": "builtin", "display_name": "张三"},
    )
    return _NaturalDraftParser(actor, anchor=date(2026, 11, 10))


def test_parse_meeting_draft():
    parser = build_parser()

    result = parser.parse("明天下午3点和李四、王五开项目复盘会，地点三楼会议室", "auto")

    assert result["draft_type"] == "meeting"
    draft = result["draft"]
    assert draft["title"] == "项目"
    assert draft["starts_at"] == "2026-11-11T15:00:00+08:00"
    assert draft["ends_at"] == "2026-11-11T16:00:00+08:00"
    assert draft["attendee_names"] == ["李四", "王五"]
    assert draft["location"] == "三楼会议室"
    assert any("会议时长" in warning for warning in parser.warnings)


def test_parse_task_draft():
    parser = build_parser()

    result = parser.parse("提醒我本周五下午提交部门周报，请尽快", "auto")

    assert result["draft_type"] == "task"
    draft = result["draft"]
    assert draft["title"] == "提交部门周报"
    assert draft["assignee_id"] == "u-zhang"
    assert draft["due_at"] == "2026-11-13T14:00:00+08:00"
    assert draft["priority"] == "high"


def test_parse_daily_schedule_draft():
    parser = build_parser()

    result = parser.parse("每天早上9点提醒我检查工单，持续30天", "auto")

    assert result["draft_type"] == "schedule"
    draft = result["draft"]
    assert draft["title"] == "检查工单"
    assert draft["frequency"] == "daily"
    assert draft["run_time"] == "09:00:00+08:00"
    assert draft["ends_at"].startswith("2026-12-10T23:59:59")
    assert draft["max_occurrences"] is None
    assert parser.warnings == []


def test_parse_weekly_schedule_draft():
    parser = build_parser()

    result = parser.parse("每周五下午6点提醒我整理周报，共4次", "auto")

    assert result["draft_type"] == "schedule"
    draft = result["draft"]
    assert draft["title"] == "整理周报"
    assert draft["frequency"] == "weekly"
    assert draft["day_of_week"] == 4
    assert draft["run_time"] == "18:00:00+08:00"
    assert draft["max_occurrences"] == 4


def test_parse_monthly_schedule_draft():
    parser = build_parser()

    result = parser.parse("每月10日上午10点提醒我核对报销，到2027年3月31日", "auto")

    assert result["draft_type"] == "schedule"
    draft = result["draft"]
    assert draft["title"] == "核对报销"
    assert draft["frequency"] == "monthly"
    assert draft["day_of_month"] == 10
    assert draft["run_time"] == "10:00:00+08:00"
    assert draft["ends_at"].startswith("2027-03-31T23:59:59")

