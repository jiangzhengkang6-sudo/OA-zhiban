"""统一智能助手 V3 的接口契约。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .assistant_v2 import (
    DraftParseResponse,
    KnowledgeSearchResponse,
    OverviewResponse,
    ReportDraftResponse,
)
from .thread import ThreadDetail

Skill = Literal[
    "auto",
    "knowledge",
    "task",
    "meeting",
    "report",
    "ticket",
    "leave",
    "overview",
    "human",
]

ResolvedSkill = Literal[
    "knowledge",
    "task",
    "meeting",
    "report",
    "ticket",
    "leave",
    "overview",
    "human",
]


class AssistantV3Message(BaseModel):
    """统一助手历史消息，仅允许对话所需角色。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=3000)


class AssistantV3ChatRequest(BaseModel):
    """统一对话请求；用户输入是数据，不能借此改变系统安全边界。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=3000)
    history: list[AssistantV3Message] = Field(default_factory=list, max_length=20)
    requested_skill: Skill = "auto"


class LegacySkillResult(BaseModel):
    """由统一助手调度、由专项技能图执行的结果。"""

    scene: Literal["ticket", "leave"]
    thread_id: str
    detail: ThreadDetail


class AssistantV3ChatResponse(BaseModel):
    """统一对话响应。"""

    reply: str
    skill: ResolvedSkill
    confidence: Literal["high", "medium", "low"] = "medium"
    citations: list[dict] = Field(default_factory=list)
    draft_proposal: DraftParseResponse | None = None
    report: ReportDraftResponse | None = None
    overview: OverviewResponse | None = None
    knowledge: KnowledgeSearchResponse | None = None
    legacy: LegacySkillResult | None = None
    follow_ups: list[str] = Field(default_factory=list)
    safety_notice: str
    generated_at: datetime

