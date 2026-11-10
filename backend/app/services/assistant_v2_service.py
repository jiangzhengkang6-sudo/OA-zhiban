"""统一 OA 智能助手 V2 服务。

本模块聚合当前用户有权访问的 OA 权威数据，生成可保存、可复核的草稿。
自然语言解析结果不会直接写入业务库，必须由用户在专项工作台再次确认后写入。
"""

from __future__ import annotations

import re
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..models.agent_thread import AgentThread
from ..models.assistant_draft import AssistantDraft
from ..models.identity import OAUser
from ..models.work_task import WorkTask
from ..models.work_task_batch import WorkTaskBatch
from ..models.work_task_event import WorkTaskEvent
from ..schemas.command import CommandEnvelope
from ..schemas.oa_meeting import MeetingCommand, MeetingCreate, MeetingFields
from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..schemas.assistant_v2 import (
    AssistantDraftResponse,
    AssistantTaskPayload,
    AssistantCard,
    AssistantSection,
    DraftCancelRequest,
    DraftConfirmRequest,
    DraftSaveRequest,
    DraftParseResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    OverviewRequest,
    OverviewResponse,
    ReportDraftRequest,
    ReportDraftResponse,
)
from . import (
    audit_service,
    idempotency_service,
    knowledge_service,
    meeting_management_service,
    oa_notification_service,
    public_mail_service,
    work_task_service,
)
from .authorization_service import require_fresh_identity, require_permission
from .identity_service import current_identity, lock_tenant

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
WEEKDAY_LABELS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
TASK_STATUS_LABELS = {
    "OPEN": "待开始",
    "IN_PROGRESS": "进行中",
    "COMPLETED": "已完成",
    "CANCELLED": "已取消",
    "ARCHIVED": "已归档",
}
PRIORITY_LABELS = {"low": "低", "normal": "普通", "high": "高"}
SAFETY_NOTICE = "助手仅汇总、检索和起草，不会自动审批、发送邮件、取消会议或通知全员；正式提交前会再次校验权限。"


def _anchor_date(value: str | None = None) -> date:
    """把客户端日期转换为上海日历日期；未传时使用当前日期。"""

    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return datetime.now(SHANGHAI_TZ).date()


def _day_bounds(anchor: date) -> tuple[datetime, datetime]:
    """返回上海时区当日起止时间，区间为 [开始, 结束)。"""

    start = datetime.combine(anchor, time.min, SHANGHAI_TZ)
    return start, start + timedelta(days=1)


def _week_bounds(anchor: date) -> tuple[datetime, datetime]:
    """返回 anchor 所在自然周的起止时间，周一开始。"""

    week_start_date = anchor - timedelta(days=anchor.weekday())
    start = datetime.combine(week_start_date, time.min, SHANGHAI_TZ)
    return start, start + timedelta(days=7)


def _has_permission(actor, resource: str, action: str) -> bool:
    """检查内置账号权限；其他身份提供方由具体服务再次校验。"""

    try:
        require_permission(actor, resource, action)
    except AppException:
        return False
    return True


def _unavailable_section(key: str, title: str, message: str) -> AssistantSection:
    return AssistantSection(key=key, title=title, available=False, message=message)


async def _task_section(session, actor, day_start: datetime, day_end: datetime) -> AssistantSection:
    if not _has_permission(actor, "work_task", "read"):
        return _unavailable_section("tasks", "我的今日待办", "当前账号没有业务任务读取权限。")
    try:
        page = await work_task_service.list_tasks(session, actor, page=1, page_size=100)
    except AppException as exc:
        return _unavailable_section("tasks", "我的今日待办", exc.message)

    now = datetime.now(SHANGHAI_TZ)
    cards: list[AssistantCard] = []
    for item in page.items:
        due_at = item.due_at
        if item.status in {"OPEN", "IN_PROGRESS"} and due_at < day_end:
            overdue = due_at < now
            cards.append(
                AssistantCard(
                    id=item.task_id,
                    type="task",
                    title=item.title,
                    subtitle=f"{'已逾期 · ' if overdue else ''}截止 {due_at.astimezone(SHANGHAI_TZ).strftime('%H:%M')}",
                    status=TASK_STATUS_LABELS.get(item.status, item.status),
                    priority=PRIORITY_LABELS.get(item.priority, item.priority),
                    time=due_at,
                    link=f"/work-tasks/{item.task_id}",
                    metadata={"overdue": overdue, "progress": item.progress},
                )
            )
    cards.sort(key=lambda card: (not card.metadata.get("overdue"), card.time or day_end))
    return AssistantSection(key="tasks", title="我的今日待办", count=len(cards), cards=cards[:8])


async def _meeting_section(session, actor, day_start: datetime, day_end: datetime) -> AssistantSection:
    if not _has_permission(actor, "meeting", "read"):
        return _unavailable_section("meetings", "我的今日会议", "当前账号没有会议读取权限。")
    try:
        rows = await meeting_management_service.list_items(session, actor)
    except AppException as exc:
        return _unavailable_section("meetings", "我的今日会议", exc.message)

    cards: list[AssistantCard] = []
    for row in rows:
        starts_at = datetime.fromisoformat(row["starts_at"])
        ends_at = datetime.fromisoformat(row["ends_at"])
        if row["state"] != "CANCELLED" and starts_at < day_end and ends_at >= day_start:
            place = row.get("location") or ("视频会议" if row.get("video_enabled") else "在线会议")
            cards.append(
                AssistantCard(
                    id=row["id"],
                    type="meeting",
                    title=row["title"],
                    subtitle=f"{starts_at.astimezone(SHANGHAI_TZ).strftime('%H:%M')}-{ends_at.astimezone(SHANGHAI_TZ).strftime('%H:%M')} · {place}",
                    status=row["state"],
                    time=starts_at,
                    link=f"/meeting-events/{row['id']}",
                    metadata={"response": next((a.get("response") for a in row.get("attendees", []) if a.get("user_id") == actor.user_id), "")},
                )
            )
    cards.sort(key=lambda card: card.time or day_end)
    return AssistantSection(key="meetings", title="我的今日会议", count=len(cards), cards=cards[:8])


async def _notification_section(session, actor) -> AssistantSection:
    if not _has_permission(actor, "notification", "read"):
        return _unavailable_section("notifications", "未读通知", "当前账号没有通知读取权限。")
    try:
        rows = await oa_notification_service.list_inbox(session, actor)
    except AppException as exc:
        return _unavailable_section("notifications", "未读通知", exc.message)

    cards = [
        AssistantCard(
            id=row["id"],
            type="notification",
            title=row["title"],
            subtitle=row.get("source_kind") or "业务提醒",
            status="未读",
            time=datetime.fromisoformat(row["created_at"]),
            link="/oa/notifications",
        )
        for row in rows
        if not row.get("read_at")
    ]
    cards.sort(key=lambda card: card.time or datetime.min.replace(tzinfo=SHANGHAI_TZ), reverse=True)
    return AssistantSection(key="notifications", title="未读通知", count=len(cards), cards=cards[:8])


async def _email_section(session, actor) -> AssistantSection:
    if not _has_permission(actor, "email", "read"):
        return _unavailable_section("emails", "待处理邮件", "当前账号没有邮件读取权限。")
    try:
        page = await public_mail_service.listing(session, actor, folder="pending", search="", page=1)
    except AppException as exc:
        return _unavailable_section("emails", "待处理邮件", exc.message)

    cards: list[AssistantCard] = []
    for row in page["items"]:
        cards.append(
            AssistantCard(
                id=row["id"],
                type="email",
                title=row["subject"],
                subtitle=f"发件人：{row['sender']}",
                status=row["status"],
                time=row.get("sent_at") or row.get("created_at"),
                link=f"/emails/{row['id']}",
            )
        )
    return AssistantSection(key="emails", title="待处理邮件", count=page["total"], cards=cards[:8])


async def overview(session, actor, payload: OverviewRequest) -> OverviewResponse:
    """生成当前用户的今日办公总览。"""

    actor = await require_fresh_identity(actor, session=session)
    anchor = _anchor_date(payload.date)
    day_start, day_end = _day_bounds(anchor)
    sections = [
        await _task_section(session, actor, day_start, day_end),
        await _meeting_section(session, actor, day_start, day_end),
        await _notification_section(session, actor),
        await _email_section(session, actor),
    ]
    counts = {section.key: section.count for section in sections}
    summary = (
        f"今日有 {counts.get('tasks', 0)} 项待办、{counts.get('meetings', 0)} 场会议、"
        f"{counts.get('notifications', 0)} 条未读通知、{counts.get('emails', 0)} 封待处理邮件。"
    )
    return OverviewResponse(
        generated_at=datetime.now(SHANGHAI_TZ),
        date=anchor.isoformat(),
        weekday=WEEKDAY_LABELS[anchor.weekday()],
        summary=summary,
        sections=sections,
        safety_notice=SAFETY_NOTICE,
    )


async def search_knowledge(session, actor, payload: KnowledgeSearchRequest) -> KnowledgeSearchResponse:
    """在当前用户有权访问的正式知识库中统一检索。"""

    actor = await require_fresh_identity(actor, session=session)
    require_permission(actor, "knowledge", "read")
    results = await knowledge_service.search(
        session,
        query=payload.query,
        permission_tags=[],
        top_k=payload.top_k,
    )
    if results:
        preview = "\n".join(f"《{item.get('title', '未知来源')}》：{item.get('content', '')}" for item in results[:3])
        answer_preview = f"根据已授权资料：\n{preview[:700]}"
    else:
        answer_preview = "未在当前账号有权访问的已发布知识库中检索到相关内容。"
    return KnowledgeSearchResponse(
        query=payload.query,
        results=results,
        answer_preview=answer_preview,
        evidence_notice="以下结果仅作为资料线索，涉及制度口径、金额、额度或流程要求时，请打开原文核对。",
    )


def _display_date(value: datetime) -> str:
    return f"{value.year}年{value.month}月{value.day}日"


def _source_record(source_type: str, item_id: str, title: str, occurred_at: datetime, status: str) -> dict[str, Any]:
    return {
        "type": source_type,
        "id": item_id,
        "title": title,
        "time": occurred_at.isoformat(),
        "status": status,
    }


async def create_report_draft(session, actor, payload: ReportDraftRequest) -> ReportDraftResponse:
    """依据任务与会议数据生成日报或周报草稿；不补造未提供的事实。"""

    actor = await require_fresh_identity(actor, session=session)
    anchor = _anchor_date(payload.date)
    period_start, period_end = (_day_bounds(anchor) if payload.report_type == "daily" else _week_bounds(anchor))
    warnings: list[str] = []
    tasks: list[Any] = []
    meetings: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

    if _has_permission(actor, "work_task", "read"):
        task_page = await work_task_service.list_tasks(session, actor, page=1, page_size=100)
        tasks = [
            item
            for item in task_page.items
            if period_start <= item.updated_at < period_end
        ]
    else:
        warnings.append("当前账号没有业务任务读取权限，草稿未包含任务进展。")

    if _has_permission(actor, "meeting", "read"):
        meeting_rows = await meeting_management_service.list_items(session, actor)
        meetings = [
            row
            for row in meeting_rows
            if period_start <= datetime.fromisoformat(row["starts_at"]) < period_end and row["state"] != "CANCELLED"
        ]
    else:
        warnings.append("当前账号没有会议读取权限，草稿未包含会议安排。")

    completed = [item for item in tasks if item.status == "COMPLETED"]
    ongoing = [item for item in tasks if item.status in {"OPEN", "IN_PROGRESS"}]
    now = datetime.now(SHANGHAI_TZ)
    overdue = [
        item
        for item in tasks
        if item.status in {"OPEN", "IN_PROGRESS"} and item.due_at < now
    ]

    for item in completed:
        sources.append(_source_record("业务任务", item.task_id, item.title, item.updated_at, "已完成"))
    for row in meetings:
        starts_at = datetime.fromisoformat(row["starts_at"])
        sources.append(_source_record("会议安排", row["id"], row["title"], starts_at, row["state"]))

    if payload.report_type == "daily":
        title = f"{_display_date(period_start)}工作日报"
        next_title = "明日计划"
    else:
        title = f"{_display_date(period_start)}至{_display_date(period_end - timedelta(days=1))}工作周报"
        next_title = "下周计划"

    def task_lines(rows: list[Any], empty_text: str) -> list[str]:
        if not rows:
            return [f"- {empty_text}"]
        return [
            f"- {item.title}（{TASK_STATUS_LABELS.get(item.status, item.status)}，负责人可见编号：{item.task_id}）"
            for item in rows
        ]

    meeting_lines = [
        f"- {row['title']}（{datetime.fromisoformat(row['starts_at']).astimezone(SHANGHAI_TZ).strftime('%m月%d日 %H:%M')}）"
        for row in meetings
    ] or ["- 本周期暂无已安排且可访问的会议。"]
    risk_lines = [f"- {item.title}已超过截止时间，请重新确认安排。" for item in overdue] or ["- 暂未从已授权任务中发现逾期事项。"]

    markdown = "\n".join([
        f"# {title}",
        "",
        f"统计区间：{period_start.astimezone(SHANGHAI_TZ).strftime('%Y-%m-%d %H:%M')} 至 {period_end.astimezone(SHANGHAI_TZ).strftime('%Y-%m-%d %H:%M')}，区间为左闭右开。",
        "",
        "## 本期完成",
        *task_lines(completed, "本周期暂无已完成任务记录。"),
        "",
        "## 进行中事项",
        *task_lines(ongoing, "本周期暂无进行中任务记录。"),
        "",
        "## 会议安排",
        *meeting_lines,
        "",
        "## 风险与需协调",
        *risk_lines,
        "",
        f"## {next_title}",
        "- 待本人补充。",
        "",
        "> 本草稿由当前账号有权访问的 OA 数据生成，提交或发送前请补充人工判断并核对来源。",
    ])

    return ReportDraftResponse(
        title=title,
        report_type=payload.report_type,
        period_start=period_start,
        period_end=period_end,
        markdown=markdown,
        sources=sources,
        warnings=warnings,
    )


class _NaturalDraftParser:
    """中文自然语言草稿解析器。

    用户输入按“数据”处理，不调用外部模型；日期、人员、地点等关键字段
    必须由后端结构化并在确认前再次校验。
    """

    WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    RELATIVE_DAYS = {"今天": 0, "今日": 0, "明天": 1, "明日": 1, "后天": 2, "大后天": 3, "昨天": -1}

    def __init__(self, actor, anchor: date | None = None) -> None:
        self.actor = actor
        self.anchor = anchor or datetime.now(SHANGHAI_TZ).date()
        self.spans: list[tuple[int, int]] = []
        self.warnings: list[str] = []
        self.day_value: date | None = None

    def parse(self, text: str, draft_type: str) -> dict[str, Any]:
        normalized = re.sub(r"\s+", " ", text.strip())
        detected_type = self._detect_type(normalized, draft_type)
        self.day_value = self._extract_day(normalized)
        start_at = self._extract_start_time(normalized)
        location, online_url, video_enabled = self._extract_location(normalized)

        if detected_type == "meeting":
            end_at = self._extract_end_time(normalized, start_at)
            attendee_names = self._extract_people(normalized)
            title = self._meeting_title(normalized)
            if start_at and self.day_value:
                start_at = start_at.replace(
                    year=self.day_value.year, month=self.day_value.month, day=self.day_value.day
                )
                end_at = end_at.replace(
                    year=self.day_value.year, month=self.day_value.month, day=self.day_value.day
                )
            elif start_at and not self.day_value:
                self.warnings.append("未识别会议日期，请人工选择。")
            if start_at and start_at < datetime.now(SHANGHAI_TZ):
                self.warnings.append("识别到的会议开始时间早于当前时间，请核对后再安排。")
            draft = {
                "title": title,
                "agenda": title,
                "starts_at": start_at.isoformat() if start_at else None,
                "ends_at": end_at.isoformat() if end_at else None,
                "host_id": self.actor.user_id,
                "host_name": self.actor.data_scope.get("display_name", ""),
                "recorder_id": self.actor.user_id,
                "recorder_name": self.actor.data_scope.get("display_name", ""),
                "attendee_ids": [],
                "attendee_names": attendee_names,
                "location": location,
                "online_url": online_url,
                "video_enabled": video_enabled,
            }
        else:
            due_at = None
            if self.day_value:
                due_time = start_at.time() if start_at else time(18, 0)
                if not start_at:
                    self.warnings.append("未识别具体时刻，截止时间已按工作日常用截止时间 18:00 预填。")
                due_at = datetime.combine(self.day_value, due_time, SHANGHAI_TZ)
            priority = self._priority(normalized)
            assignee_id, assignee_name = self._extract_assignee(normalized)
            title = self._task_title(normalized)
            draft = {
                "title": title,
                "assignee_id": assignee_id,
                "assignee_name": assignee_name,
                "due_at": due_at.isoformat() if due_at else None,
                "priority": priority,
                "sensitive": False,
            }
        return {"draft_type": detected_type, "draft": draft}

    def _detect_type(self, text: str, draft_type: str) -> str:
        if draft_type != "auto":
            return draft_type
        if re.search(r"会议|开会|评审|沟通会|研讨会|复盘会|约谈|例会", text):
            return "meeting"
        if re.search(r"任务|提醒|待办|跟进|完成|提交|整理|核对|催|安排我", text):
            return "task"
        self.warnings.append("未能根据关键词明确判断类型，已先按任务草稿处理。")
        return "task"

    def _remember_span(self, match: re.Match[str]) -> None:
        self.spans.append(match.span())

    def _extract_day(self, text: str) -> date | None:
        patterns = (
            (r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", self._explicit_day),
            (r"(\d{1,2})月(\d{1,2})日", self._month_day),
            (r"(?:下|本周|这周|本)?(?:星期|周|礼拜)([一二三四五六七日天])", self._weekday),
            (r"今天|今日|明天|明日|后天|大后天|昨天", self._relative_day),
        )
        for pattern, resolver in patterns:
            match = re.search(pattern, text)
            if match:
                self._remember_span(match)
                return resolver(match)
        return None

    def _explicit_day(self, match: re.Match[str]) -> date:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def _month_day(self, match: re.Match[str]) -> date:
        target = date(self.anchor.year, int(match.group(1)), int(match.group(2)))
        if target < self.anchor:
            return date(self.anchor.year + 1, target.month, target.day)
        return target

    def _weekday(self, match: re.Match[str]) -> date:
        target_index = self.WEEKDAYS[match.group(1)]
        raw = match.group(0)
        base = self.anchor - timedelta(days=self.anchor.weekday())
        target = base + timedelta(days=target_index)
        if raw.startswith("下"):
            target += timedelta(days=7)
        elif not re.search(r"本|这", raw) and target < self.anchor:
            target += timedelta(days=7)
        return target

    def _relative_day(self, match: re.Match[str]) -> date:
        return self.anchor + timedelta(days=self.RELATIVE_DAYS[match.group(0)])

    def _period_adjust(self, period: str | None, hour: int) -> int:
        if period in {"下午", "傍晚", "晚上", "晚"} and hour < 12:
            return hour + 12
        if period == "中午" and hour < 12:
            return 12
        if period in {"早上", "上午", "早晨"} and hour == 12:
            return 0
        return hour

    def _period_default(self, period: str) -> int:
        return {
            "早上": 9,
            "早晨": 9,
            "上午": 10,
            "中午": 12,
            "下午": 14,
            "傍晚": 18,
            "晚上": 19,
            "晚": 19,
        }[period]

    def _time_from_match(self, match: re.Match[str]) -> datetime:
        period = match.group(1)
        if len(match.groups()) == 1:
            hour = self._period_default(period)
            minute = 0
            self.warnings.append(f"未识别具体时刻，已按“{period}”的常用办公时间预填，请核对。")
        elif match.group(2) is not None:
            hour = int(match.group(2))
            minute = int(match.group(3) or 0)
        else:
            hour = self._period_default(period)
            minute = 0
            self.warnings.append(f"未识别具体时刻，已按“{period}”的常用办公时间预填，请核对。")
        hour = self._period_adjust(period, hour)
        return datetime(2000, 1, 1, hour, minute, tzinfo=SHANGHAI_TZ)

    def _extract_start_time(self, text: str) -> datetime | None:
        patterns = (
            r"(上午|早上|早晨|中午|下午|傍晚|晚上|晚)?\s*(\d{1,2})[:：](\d{1,2})",
            r"(上午|早上|早晨|中午|下午|傍晚|晚上|晚)?\s*(\d{1,2})\s*点\s*(半|(\d{1,2})\s*分?)?",
            r"(上午|早上|早晨|中午|下午|傍晚|晚上|晚)(?!\d)",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                self._remember_span(match)
                if "点" in pattern and match.group(2) is not None:
                    period = match.group(1)
                    hour = self._period_adjust(period, int(match.group(2)))
                    minute = 30 if match.group(3) == "半" else int(match.group(4) or 0)
                    return datetime(2000, 1, 1, hour, minute, tzinfo=SHANGHAI_TZ)
                return self._time_from_match(match)
        return None

    def _extract_end_time(self, text: str, start_at: datetime | None) -> datetime:
        end_clock = re.search(r"(?:到|至)\s*(上午|早上|中午|下午|傍晚|晚上|晚)?\s*(\d{1,2})(?:[:：点](\d{1,2}))?", text)
        if end_clock:
            self._remember_span(end_clock)
            period, hour_text, minute_text = end_clock.groups()
            hour = self._period_adjust(period, int(hour_text))
            minute = int(minute_text or 0)
            return datetime(2000, 1, 1, hour, minute, tzinfo=SHANGHAI_TZ)

        half_hour = re.search(r"一个半小时|半小时", text)
        if half_hour:
            self._remember_span(half_hour)
            duration = timedelta(minutes=30 if half_hour.group(0) == "半小时" else 90)
        else:
            duration_match = re.search(r"(\d+(?:\.\d+)?)\s*个?(?:小时|钟头)|(\d+)\s*分钟", text)
            if duration_match:
                self._remember_span(duration_match)
                if duration_match.group(2):
                    duration = timedelta(minutes=int(duration_match.group(2)))
                else:
                    duration = timedelta(hours=float(duration_match.group(1)))
            else:
                duration = timedelta(hours=1)
                self.warnings.append("未识别会议时长，已按 1 小时预填，请核对。")

        base = start_at or datetime(2000, 1, 1, 10, 0, tzinfo=SHANGHAI_TZ)
        return base + duration

    def _extract_location(self, text: str) -> tuple[str, str, bool]:
        location, online_url = "", ""
        video_enabled = bool(re.search(r"视频会议", text))
        url = re.search(r"https?://[^\s，。；;]+", text)
        if url:
            self._remember_span(url)
            online_url = url.group(0)
        explicit = re.search(r"(?:地点|会议室|在)\s*[:：是]?\s*([\u4e00-\u9fa5A-Za-z0-9\-]{2,30}会议室)", text)
        if explicit:
            self._remember_span(explicit)
            location = explicit.group(1)
        if re.search(r"腾讯会议|线上会议|在线会议|远程会议|线上开", text):
            online_url = online_url
            if not location:
                location = "线上会议"
        return location, online_url, video_enabled

    def _extract_people(self, text: str) -> list[str]:
        match = re.search(
            r"(?:和|与|跟|同)([\u4e00-\u9fa5]{2,4}(?:[、，和][\u4e00-\u9fa5]{2,4})*)"
            r"(?=开|讨论|评审|沟通|会议|研讨|复盘|约谈|[，。；;]|$)",
            text,
        )
        if not match:
            return []
        self._remember_span(match)
        raw = match.group(1)
        names = [part.strip() for part in re.split(r"[、，和]", raw) if part.strip()]
        # 常见词语不是确定人员，仍展示给用户，但不生成任何用户 ID。
        names = names[:30]
        if names:
            self.warnings.append("参会人员姓名需在会议工作台中人工选择并核对。")
        return names

    def _extract_assignee(self, text: str) -> tuple[str | None, str]:
        if re.search(r"提醒我|我要|我需要|本人", text):
            return self.actor.user_id, self.actor.data_scope.get("display_name", "")
        match = re.search(r"(?:让|叫|请|派|交给|分配给|分配给了)\s*([\u4e00-\u9fa5]{2,4})(?:去|负责)?", text)
        if match:
            self._remember_span(match)
            self.warnings.append("负责人姓名需人工匹配为正式账号后才能创建任务。")
            return None, match.group(1)
        return None, ""

    def _priority(self, text: str) -> str:
        match = re.search(r"紧急|尽快|马上|立刻|重要|高优先级", text)
        if match:
            self._remember_span(match)
            return "high"
        match = re.search(r"不急|低优先级|慢慢", text)
        if match:
            self._remember_span(match)
            return "low"
        return "normal"

    def _remove_spans(self, text: str) -> str:
        if not self.spans:
            return text
        result: list[str] = []
        last = 0
        for start, end in sorted(self.spans):
            result.append(text[last:start])
            last = max(last, end)
        result.append(text[last:])
        return "".join(result)

    def _clean(self, text: str) -> str:
        text = self._remove_spans(text)
        text = self._strip_filler(text)
        return text.strip(" ，。；;")

    def _strip_filler(self, text: str) -> str:
        return re.sub(
            r"帮我|提醒我|请|安排一下|安排个|安排一场|开个|开一场|一个|一场|^[，。；;\s]+|[，。；;\s]+$",
            "",
            text,
        )

    def _meeting_title(self, text: str) -> str:
        patterns = (
            r"关于(.+?)(?:的)?(?:会议|评审|沟通会|研讨会|复盘会|例会)",
            r"(?:开|安排|预约|组织|召开)(?:一个|一场)?(.+?)(?:会议|评审|沟通会|研讨会|复盘会|例会)",
            r"(.+?)(?:会议|评审|沟通会|研讨会|复盘会|例会)",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match and match.group(1).strip():
                return self._strip_filler(match.group(1)).strip(" ，。；;")[:255]
        title = self._clean(text)
        return (title or text.strip())[:255]

    def _task_title(self, text: str) -> str:
        title = self._clean(text)[:255]
        return title or text.strip()[:255]


async def parse_natural_draft(session, actor, payload) -> DraftParseResponse:
    """把自然语言转换为任务或会议草稿，不执行写入。"""

    actor = await require_fresh_identity(actor, session=session)
    parser = _NaturalDraftParser(actor, _anchor_date(None))
    parsed = parser.parse(payload.text, payload.draft_type)
    draft_type = parsed["draft_type"]
    draft = parsed["draft"]
    missing_required: list[str] = []

    if draft_type == "meeting":
        require_permission(actor, "meeting", "read")
        if not _has_permission(actor, "meeting", "write"):
            parser.warnings.append("当前账号没有会议安排写入权限，草稿暂不能直接创建为正式会议。")
        field_labels = {
            "title": "会议主题",
            "starts_at": "开始时间",
            "ends_at": "结束时间",
            "attendee_ids": "参会人员",
        }
        for field, label in field_labels.items():
            if not draft.get(field):
                missing_required.append(label)
        if not (draft.get("location") or draft.get("online_url") or draft.get("video_enabled")):
            missing_required.append("会议地点或在线方式")
    else:
        require_permission(actor, "work_task", "read")
        if not _has_permission(actor, "work_task", "write"):
            parser.warnings.append("当前账号没有业务任务写入权限，草稿暂不能直接创建为正式任务。")
        for field, label in (("title", "任务标题"), ("assignee_id", "负责人"), ("due_at", "截止时间")):
            if not draft.get(field):
                missing_required.append(label)

    confidence = "high" if not missing_required and not parser.warnings else "medium" if draft_type and payload.draft_type != "auto" or not missing_required else "low"
    return DraftParseResponse(
        draft_type=draft_type,
        confidence=confidence,
        draft=draft,
        missing_required=missing_required,
        warnings=parser.warnings,
        confirmation_notice="当前结果只是草稿；后续创建或安排前，系统会再次校验人员权限、租户隔离、冲突与幂等状态。",
    )


async def options(session, actor, draft_type: str) -> dict[str, Any]:
    """返回草稿可选人员；任务和会议分别执行各自的权限边界。"""

    actor = await require_fresh_identity(actor, session=session)
    if draft_type == "meeting":
        return await meeting_management_service.options(session, actor)

    require_permission(actor, "work_task", "write")
    users: list[dict[str, Any]] = []
    rows = (
        await session.scalars(
            select(OAUser)
            .where(
                OAUser.tenant_id == actor.tenant_id,
                OAUser.status == "active",
            )
            .order_by(OAUser.display_name, OAUser.id)
        )
    ).all()
    for user in rows:
        member = await current_identity(session, user)
        try:
            require_permission(member, "work_task", "read")
        except AppException:
            continue
        users.append(
            {
                "id": member.user_id,
                "display_name": member.data_scope.get("display_name", member.user_id),
                "department_id": member.depts[0] if member.depts else None,
            }
        )
    return {"users": users}


async def _validate_formal_identity(actor) -> Any:
    """确认第二阶段写入能力只对正式身份账号开放。"""

    actor = await require_fresh_identity(actor)
    if actor.data_scope.get("identity_provider") != "builtin":
        raise AppException(
            ErrorCode.BAD_REQUEST,
            "草稿保存与确认仅支持正式身份账号。",
            http_status=422,
        )
    return actor


def _risk_warning(priority: str, sensitive: bool, cross_department: bool) -> str | None:
    if priority == "high":
        return "高优先级任务确认时需勾选风险确认。"
    if sensitive:
        return "敏感任务确认时需勾选风险确认。"
    if cross_department:
        return "跨部门任务确认时需勾选风险确认。"
    return None


async def _validate_saved_payload(
    session,
    actor,
    draft_type: str,
    raw: dict[str, Any],
) -> tuple[Any, list[str]]:
    """把草稿内容转换为后端强类型结构，并执行实时权限校验。"""

    warnings: list[str] = []
    if draft_type == "task":
        require_permission(actor, "work_task", "write")
        payload = AssistantTaskPayload.model_validate(raw)
        from ..providers.identity import IdentityResolver

        target = await IdentityResolver().resolve(payload.assignee_id, session=session)
        if target is None or target.tenant_id != actor.tenant_id:
            raise AppException(
                ErrorCode.BAD_REQUEST,
                "负责人不存在或不属于当前租户。",
                http_status=422,
            )
        require_permission(target, "work_task", "read")
        cross_department = not set(target.depts).intersection(actor.depts)
        warning = _risk_warning(payload.priority, payload.sensitive, cross_department)
        if warning:
            warnings.append(warning)
        return payload, warnings

    require_permission(actor, "meeting", "write")
    payload = MeetingFields.model_validate(raw)
    await meeting_management_service.members(session, actor, payload)
    return payload, warnings


def _draft_response(row: AssistantDraft) -> AssistantDraftResponse:
    return AssistantDraftResponse(
        id=row.id,
        draft_type=row.draft_type,
        status=row.status,
        payload=row.payload,
        missing_required=row.missing_required,
        warnings=row.warnings,
        result=row.result,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def save_draft(session, actor, payload: DraftSaveRequest) -> AssistantDraftResponse:
    """保存可复核草稿，此步骤不写入任务或会议。"""

    actor = await require_fresh_identity(actor, session=session)
    if actor.data_scope.get("identity_provider") != "builtin":
        raise AppException(
            ErrorCode.BAD_REQUEST,
            "草稿保存仅支持正式身份账号。",
            http_status=422,
        )
    await lock_tenant(session, actor.tenant_id)
    structured_payload, warnings = await _validate_saved_payload(
        session, actor, payload.draft_type, payload.draft
    )
    draft = AssistantDraft(
        id=str(uuid4()),
        tenant_id=actor.tenant_id,
        owner_id=actor.user_id,
        draft_type=payload.draft_type,
        status="DRAFT",
        payload=structured_payload.model_dump(mode="json"),
        missing_required=[],
        warnings=warnings,
        result={},
    )
    session.add(draft)
    await session.flush()
    await audit_service.audit(
        session,
        "assistant_draft_saved",
        actor_id=actor.user_id,
        target_type="assistant_draft",
        target_id=draft.id,
        input_summary={"draft_type": draft.draft_type},
    )
    await session.refresh(draft)
    return _draft_response(draft)


async def _owned_draft(
    session,
    actor,
    draft_id: str,
    *,
    lock: bool = False,
) -> AssistantDraft:
    query = select(AssistantDraft).where(
        AssistantDraft.tenant_id == actor.tenant_id,
        AssistantDraft.id == draft_id,
        AssistantDraft.owner_id == actor.user_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(query)
    if row is None:
        raise AppException(ErrorCode.NOT_FOUND, "草稿不存在或不可访问", http_status=404)
    return row


async def _confirm_task_draft(
    session,
    actor,
    draft: AssistantDraft,
    payload,
) -> None:
    """确认后创建一条正式业务任务。"""

    task_payload = AssistantTaskPayload.model_validate(draft.payload)
    await work_task_service._assignee(
        session,
        actor,
        task_payload.assignee_id,
        task_payload.priority,
        task_payload.sensitive,
        payload.risk_acknowledged,
    )
    source_ref = f"assistant:{draft.id}:1"
    snapshot = {
        "ref": source_ref,
        "source_type": "assistant",
        "source_id": draft.id,
        "version": "1",
        "title": task_payload.title,
        "content": task_payload.title,
        "action_items": [],
    }
    thread = AgentThread(
        tenant_id=actor.tenant_id,
        user_id=actor.user_id,
        scene="assistant_v2",
        intent="create_task",
        status="CONFIRMED",
    )
    session.add(thread)
    await session.flush()
    batch = WorkTaskBatch(
        batch_id="WTB-" + uuid4().hex[:12].upper(),
        thread_id=thread.id,
        tenant_id=actor.tenant_id,
        owner_id=actor.user_id,
        source_type="assistant",
        source_id=draft.id,
        source_version="1",
        source_snapshot=snapshot,
        idempotency_key=payload.operation_id,
    )
    session.add(batch)
    await session.flush()
    task_id = "WT-" + uuid4().hex[:12].upper()
    task = WorkTask(
        id=uuid4(),
        task_id=task_id,
        batch_id=batch.id,
        tenant_id=actor.tenant_id,
        creator_id=actor.user_id,
        assignee_id=task_payload.assignee_id,
        source_type="assistant",
        source_id=draft.id,
        source_version="1",
        candidate_id=draft.id,
        source_refs=[source_ref],
        title=task_payload.title,
        priority=task_payload.priority,
        sensitive=task_payload.sensitive,
        due_at=task_payload.due_at,
        status="OPEN",
        progress=0,
        version=1,
        deadline_version=1,
    )
    session.add(task)
    await session.flush()
    session.add(
        WorkTaskEvent(
            task_id=task.id,
            actor_id=actor.user_id,
            action="created",
            version=1,
            details={"assistant_draft_id": draft.id},
        )
    )
    thread.business_id = task_id
    draft.result = {"task_id": task_id}
    await audit_service.audit(
        session,
        "assistant_task_created",
        thread_id=thread.id,
        business_id=task_id,
        actor_id=actor.user_id,
        target_type="work_task",
        target_id=task_id,
    )


async def _confirm_meeting_draft(
    session,
    actor,
    draft: AssistantDraft,
) -> None:
    """确认后创建并发布一场正式会议。"""

    meeting_payload = MeetingFields.model_validate(draft.payload)
    save_operation_id = str(
        uuid5(NAMESPACE_URL, f"{actor.tenant_id}:{draft.id}:meeting-save")
    )
    save_outcome = await meeting_management_service.save(
        session,
        actor,
        MeetingCreate(
            **meeting_payload.model_dump(mode="json"),
            operation_id=save_operation_id,
        ),
    )
    meeting_id = save_outcome.result["id"]
    publish_operation_id = str(
        uuid5(NAMESPACE_URL, f"{actor.tenant_id}:{draft.id}:meeting-publish")
    )
    await meeting_management_service.transition(
        session,
        actor,
        meeting_id,
        MeetingCommand(
            operation_id=publish_operation_id,
            expected_revision=save_outcome.result["revision"],
        ),
        "publish",
    )
    draft.result = {"meeting_id": meeting_id, "state": "SCHEDULED"}
    await audit_service.audit(
        session,
        "assistant_meeting_published",
        business_id=meeting_id,
        actor_id=actor.user_id,
        target_type="oa_meeting",
        target_id=meeting_id,
    )


async def confirm_draft(
    session,
    actor,
    draft_id: str,
    payload: DraftConfirmRequest,
) -> AssistantDraftResponse:
    """确认草稿并写入正式业务数据。"""

    actor = await require_fresh_identity(actor, session=session)
    if actor.data_scope.get("identity_provider") != "builtin":
        raise AppException(
            ErrorCode.BAD_REQUEST,
            "草稿确认仅支持正式身份账号。",
            http_status=422,
        )
    if not payload.metadata_confirmed:
        raise AppException(
            ErrorCode.BAD_REQUEST,
            "请先核对会议或任务内容，并勾选信息确认。",
            http_status=422,
        )

    await lock_tenant(session, actor.tenant_id)
    draft = await _owned_draft(session, actor, draft_id, lock=True)
    await session.refresh(draft)
    if draft.status == "CONFIRMED":
        return _draft_response(draft)
    if draft.status != "DRAFT":
        raise AppException(
            ErrorCode.INVALID_STATE,
            "当前草稿不可确认。",
            http_status=422,
        )

    # 再次执行强类型校验，防止保存后人员、权限或时间状态发生变化。
    await _validate_saved_payload(session, actor, draft.draft_type, draft.payload)
    envelope = CommandEnvelope(
        command_id=uuid4(),
        idempotency_key=payload.operation_id,
        actor_id=actor.user_id,
        tenant_id=actor.tenant_id,
        resource_type="assistant_draft",
        resource_id=draft.id,
        trace_id=uuid4().hex,
        payload={
            "draft_type": draft.draft_type,
            "payload": draft.payload,
            "metadata_confirmed": payload.metadata_confirmed,
            "risk_acknowledged": payload.risk_acknowledged,
        },
    )
    command, fresh = await idempotency_service.claim(session, envelope)
    if fresh:
        if draft.draft_type == "task":
            await _confirm_task_draft(session, actor, draft, payload)
        else:
            await _confirm_meeting_draft(session, actor, draft)
        draft.status = "CONFIRMED"
        draft.confirmed_at = datetime.now(timezone.utc)
        await session.flush()
        await idempotency_service.complete(
            session,
            command,
            {"result": draft.result},
        )
        await session.refresh(draft)
    return _draft_response(draft)


async def list_saved_drafts(session, actor) -> list[AssistantDraftResponse]:
    actor = await require_fresh_identity(actor, session=session)
    rows = (
        await session.scalars(
            select(AssistantDraft)
            .where(
                AssistantDraft.tenant_id == actor.tenant_id,
                AssistantDraft.owner_id == actor.user_id,
            )
            .order_by(AssistantDraft.updated_at.desc())
            .limit(100)
        )
    ).all()
    return [_draft_response(row) for row in rows]


async def get_saved_draft(
    session,
    actor,
    draft_id: str,
) -> AssistantDraftResponse:
    actor = await require_fresh_identity(actor, session=session)
    return _draft_response(await _owned_draft(session, actor, draft_id))


async def cancel_saved_draft(
    session,
    actor,
    draft_id: str,
    payload: DraftCancelRequest,
) -> AssistantDraftResponse:
    actor = await require_fresh_identity(actor, session=session)
    await lock_tenant(session, actor.tenant_id)
    draft = await _owned_draft(session, actor, draft_id, lock=True)
    if draft.status != "DRAFT":
        raise AppException(
            ErrorCode.INVALID_STATE,
            "仅未确认草稿可以取消。",
            http_status=422,
        )
    draft.status = "CANCELLED"
    draft.notes = payload.reason
    draft.missing_required = []
    draft.warnings = []
    await session.flush()
    await audit_service.audit(
        session,
        "assistant_draft_cancelled",
        actor_id=actor.user_id,
        target_type="assistant_draft",
        target_id=draft.id,
        output_summary={"reason": payload.reason},
    )
    await session.refresh(draft)
    return _draft_response(draft)

