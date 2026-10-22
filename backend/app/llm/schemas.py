"""
OA 智能体管理系统 - LLM 结构化输出契约。

定义模型结构化输出的 Pydantic schema（意图分类、工单抽取、驳回摘要等），
供业务节点调用 LLMClient.structured() 时使用，确保节点间只传递强类型对象。
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class IntentClassification(BaseModel):
    """SuperAgent 意图分类输出。

    Attributes:
        intent: 识别意图（leave/faq/ticket/human/unknown）。
        confidence: 置信度 [0,1]。
    """

    intent: Literal["leave", "faq", "ticket", "human", "unknown"]
    confidence: float = Field(ge=0, le=1)


class TicketExtraction(BaseModel):
    """工单字段抽取输出。

    Attributes:
        category: 类别。
        priority: 优先级（low/medium/high）。
        impact: 影响范围。
        summary: 问题摘要。
        missing_fields: 仍缺失、需追问的字段。
    """

    category: str = "其他"
    priority: Literal["low", "medium", "high"] = "medium"
    impact: str = "个人"
    summary: str = ""
    missing_fields: list[str] = Field(default_factory=list)


class RejectSummary(BaseModel):
    """驳回理由结构化摘要输出。

    Attributes:
        summary: 面向员工的驳回说明。
        fix_hints: 修改建议列表。
    """

    summary: str = ""
    fix_hints: list[str] = Field(default_factory=list)


class AnswerWithSources(BaseModel):
    """FAQ 带来源回答输出。

    Attributes:
        answer: 基于检索证据生成的回答。
        sources: 来源引用列表（文档/切片/段落定位）。
        confidence: 回答置信度。
    """

    answer: str = ""
    sources: list[dict] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)