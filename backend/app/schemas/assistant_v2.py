"""统一 OA 智能助手 V2 的接口数据结构。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    """日报或周报草稿生成请求。"""

    report_type: Literal["daily", "weekly"]
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
    """日报或周报草稿响应。"""

    title: str
    report_type: Literal["daily", "weekly"]
    period_start: datetime
    period_end: datetime
    markdown: str
    sources: list[dict[str, Any]]
    warnings: list[str]


class DraftParseResponse(BaseModel):
    """自然语言草稿解析响应。"""

    draft_type: Literal["task", "meeting"]
    confidence: Literal["high", "medium", "low"]
    draft: dict[str, Any]
    missing_required: list[str]
    warnings: list[str]
    confirmation_notice: str

