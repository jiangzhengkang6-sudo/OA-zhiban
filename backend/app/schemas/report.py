"""Bounded, registry-only report plans and immutable review commands."""
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MetricId = Literal["ticket_volume", "approval_outcomes", "work_task_progress"]


class ReportPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metrics: list[MetricId] = Field(min_length=1, max_length=3)
    start: datetime
    end: datetime
    grain: Literal["day"] = "day"
    scope: Literal["own", "department", "tenant"] = "own"
    metric_version: Literal[1] = 1

    @field_validator("start", "end", mode="before")
    @classmethod
    def normalize_date(cls, value):
        if isinstance(value, str) and len(value) == 10:
            value = datetime.combine(date.fromisoformat(value), time.min, ZoneInfo("Asia/Shanghai"))
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("time boundaries require a timezone or Shanghai calendar date")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def bounded(self):
        if self.end <= self.start or self.end - self.start > timedelta(days=366):
            raise ValueError("range must be positive and at most 366 days")
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("duplicate metrics")
        if (self.end - self.start).total_seconds() % 86400 or any(
            boundary.astimezone(ZoneInfo("Asia/Shanghai")).time() != time.min for boundary in (self.start, self.end)
        ):
            raise ValueError("day reports require Shanghai midnight boundaries")
        return self

    @property
    def previous_start(self):
        return self.start - (self.end - self.start)

    @property
    def previous_end(self):
        return self.start


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    subject: str = Field(min_length=1, max_length=255)
    plan: ReportPlan
    idempotency_key: str = Field(min_length=1, max_length=128)


class ReportDraftDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    summary: str = Field(min_length=1, max_length=8000)
    metric_refs: list[MetricId] = Field(min_length=1, max_length=3)
    possible_causes: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("possible_causes")
    @classmethod
    def bounded_causes(cls, values):
        if any(not value.strip() or len(value) > 500 for value in values):
            raise ValueError("cause text must contain at most 500 characters")
        return values


class ReportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)


class ReportPlanApproval(ReportCommand):
    plan_confirmed: bool = False


class ReportDraftUpdate(ReportCommand):
    draft: ReportDraftDTO


class ReportPublication(ReportCommand):
    definitions_confirmed: bool = False
    causes_acknowledged: bool = False


class ReportSummary(BaseModel):
    report_id: str
    thread_id: str
    subject: str
    status: str
    version: int
    available_actions: list[str]
    created_at: datetime
    updated_at: datetime


class ReportResponse(ReportSummary):
    plan: ReportPlan
    plan_confirmation: dict | None = None
    snapshot: dict | None = None
    draft: ReportDraftDTO | None = None
    publication: dict | None = None
    error: dict | None = None
    external_writes: Literal[False] = False


class ReportVersionDTO(BaseModel):
    version: int
    snapshot: dict
    draft: ReportDraftDTO
    edited_by: str | None
    created_at: datetime


class ReportPage(BaseModel):
    items: list[ReportSummary]
    total: int
    page: int
    page_size: int
