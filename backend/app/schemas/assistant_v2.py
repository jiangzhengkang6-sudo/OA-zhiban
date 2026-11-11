"""统一 OA 智能助手 V2 的接口数据结构。"""

from datetime import datetime, time, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .oa_meeting import MeetingFields

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
SHANGHAI_OFFSET = timezone(timedelta(hours=8))


class AssistantV2Request(BaseModel):
    """统一助手请求基类，禁止客户端传入未声明字段。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OverviewRequest(AssistantV2Request):
    """办公总览查询条件，日期使用上海日历。"""

    date: str | None = Field(default=None, max_length=10)

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("日期格式必须为 YYYY-MM-DD") from exc
        return value


class KnowledgeSearchRequest(AssistantV2Request):
    """统一知识检索请求。"""

    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


class ReportDraftRequest(AssistantV2Request):
    """日报、周报或月报草稿生成请求。"""

    report_type: Literal["daily", "weekly", "monthly"]
    date: str | None = Field(default=None, max_length=10)

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
                datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("日期格式必须为 YYYY-MM-DD") from exc
        return value


class DraftParseRequest(AssistantV2Request):
    """自然语言任务或会议草稿解析请求。"""

    text: str = Field(min_length=1, max_length=3000)
    draft_type: Literal["auto", "task", "meeting"] = "auto"


class AssistantTaskPayload(BaseModel):
    """助手任务创建草稿的结构化内容。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255)
    assignee_id: str = Field(min_length=1, max_length=64)
    due_at: datetime
    priority: Literal["low", "normal", "high"] = "normal"
    sensitive: bool = False

    @field_validator("due_at")
    @classmethod
    def aware_due_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("截止时间必须包含时区")
        return value


class AssistantTaskActionPayload(BaseModel):
    """助手对已有任务执行操作的草稿内容。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    operation: Literal["complete", "cancel"]
    task_id: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(default=0, ge=0)
    comment: str = Field(default="", max_length=2000)


class AssistantSchedulePayload(BaseModel):
    """助手周期任务草稿的结构化内容，仅允许本人、低风险规则。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=255)
    frequency: Literal["daily", "weekly", "monthly"]
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=28)
    run_time: time
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_occurrences: int | None = Field(default=None, ge=1, le=100)
    priority: Literal["low", "normal"] = "normal"
    sensitive: Literal[False] = False

    @field_validator("run_time")
    @classmethod
    def shanghai_run_time(cls, value: time) -> time:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None:
            raise ValueError("执行时间必须包含上海时区")
        if offset != SHANGHAI_OFFSET.utcoffset(None):
            raise ValueError("执行时间必须使用上海时区 UTC+08:00")
        # time.isoformat() 对 ZoneInfo 可能不写入偏移，周期规则统一使用固定 +08:00。
        return value.replace(tzinfo=SHANGHAI_OFFSET)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def aware_bound(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("周期起止时间必须包含时区")
        return value


class AssistantMeetingActionPayload(BaseModel):
    """助手对已有会议执行操作的草稿内容。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    operation: Literal["cancel"]
    meeting_id: str = Field(min_length=1, max_length=64)
    expected_revision: int = Field(default=0, ge=0)
    reason: str = Field(min_length=1, max_length=1000)


class AssistantExistingItem(BaseModel):
    """助手可操作的已有事项。"""

    id: str
    title: str
    status: str
    version: int
    time: datetime | None = None
    available_actions: list[str] = Field(default_factory=list)


class DraftSaveRequest(AssistantV2Request):
    """保存助手草稿请求。"""

    draft_type: Literal["task", "meeting", "schedule"]
    draft: dict[str, Any]


class DraftConfirmRequest(AssistantV2Request):
    """确认执行助手草稿请求。"""

    operation_id: str = Field(min_length=1, max_length=48)
    metadata_confirmed: bool
    risk_acknowledged: bool = False


class DraftCancelRequest(AssistantV2Request):
    """取消助手草稿请求。"""

    reason: str = Field(default="", max_length=500)


class AssistantCard(BaseModel):
    """统一业务卡片，字段均来自当前用户有权访问的权威数据。"""

    id: str
    type: str
    title: str
    subtitle: str = ""
    description: str = ""
    status: str = ""
    priority: str = ""
    time: datetime | None = None
    link: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantSection(BaseModel):
    """总览分区。"""

    key: str
    title: str
    available: bool = True
    count: int = 0
    message: str = ""
    cards: list[AssistantCard] = Field(default_factory=list)


class OverviewResponse(BaseModel):
    """办公总览响应。"""

    generated_at: datetime
    date: str
    weekday: str
    summary: str
    sections: list[AssistantSection]
    safety_notice: str


class KnowledgeSearchResponse(BaseModel):
    """统一知识检索响应。"""

    query: str
    results: list[dict[str, Any]]
    answer_preview: str
    evidence_notice: str


class ReportDraftResponse(BaseModel):
    """日报、周报或月报草稿响应。"""

    title: str
    report_type: Literal["daily", "weekly", "monthly"]
    period_start: datetime
    period_end: datetime
    markdown: str
    sources: list[dict[str, Any]]
    warnings: list[str]


class DraftParseResponse(BaseModel):
    """自然语言草稿解析响应。"""

    draft_type: Literal["task", "meeting", "schedule"]
    confidence: Literal["high", "medium", "low"]
    draft: dict[str, Any]
    missing_required: list[str]
    warnings: list[str]
    confirmation_notice: str


class AssistantDraftResponse(BaseModel):
    """已保存助手草稿响应。"""

    id: str
    draft_type: Literal["task", "meeting", "schedule"]
    status: Literal["DRAFT", "CONFIRMED", "CANCELLED"]
    payload: dict[str, Any]
    missing_required: list[str]
    warnings: list[str]
    result: dict[str, Any]
    notes: str = ""
    created_at: datetime
    updated_at: datetime


class AssistantScheduleResponse(BaseModel):
    """已启用周期规则响应。"""

    id: str
    status: Literal["ACTIVE", "PAUSED", "CANCELLED", "COMPLETED"]
    title: str
    frequency: Literal["daily", "weekly", "monthly"]
    day_of_week: int | None
    day_of_month: int | None
    run_time: time
    next_run_at: datetime | None
    last_run_at: datetime | None
    starts_at: datetime | None
    ends_at: datetime | None
    max_occurrences: int | None
    occurrence_count: int
    template: dict[str, Any]
    created_at: datetime
    updated_at: datetime

