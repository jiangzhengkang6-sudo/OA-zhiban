"""
OA 智能体管理系统 - 确定性 Mock LLM 实现。

MVP 默认模型实现：不调用网络，基于关键词规则返回确定性结构化结果，保证离线可跑通
两条业务闭环、E2E 可重复。真实模型接入（ArkLLM）时按 .env 切换。
"""

from typing import TypeVar

from pydantic import BaseModel

from .base import LLMClient
from .schemas import (
    IntentClassification,
    RejectSummary,
    TicketExtraction,
)

TModel = TypeVar("TModel", bound=BaseModel)

# 意图关键词表（确定性分类）
_INTENT_KEYWORDS = {
    "faq": [
        "是什么", "怎么", "如何", "请问", "制度", "规定", "政策", "流程",
        "有哪些", "条件", "多久", "多长时间", "提前", "多少", "为什么",
        "能否", "可以吗", "是否", "吗？", "吗?",
    ],
    "leave": ["请假", "年假", "病假", "事假", "调休", "leave", "审批"],
    "ticket": ["工单", "报修", "故障", "问题", "申请", "设备", "账号", "权限", "开不了机", "无法"],
    "human": ["人工", "转人工", "找人", "客服"],
}


class MockLLM:
    """确定性 Mock LLM 客户端。"""

    async def chat(self, messages: list[dict], *, model: str | None = None) -> str:
        """返回固定文案（基于最后一条用户消息）。

        Args:
            messages: 消息列表。
            model: 模型名（忽略）。

        Returns:
            str: 固定文案。
        """
        last = MockLLM._last_user_text(messages)
        return f"[Mock 回答] 已收到您的问题：{last[:50]}"

    async def structured(
        self, messages: list[dict], schema: type[TModel], *, model: str | None = None,
        max_tokens: int | None = None
    ) -> TModel:
        """按 schema 类型返回确定性结构化结果。

        Args:
            messages: 消息列表。
            schema: 目标 Pydantic 模型。
            model: 模型名（忽略）。

        Returns:
            TModel: 校验后的结构化对象。
        """
        text = MockLLM._last_user_text(messages)
        # 意图分类
        if schema is IntentClassification:
            intent, confidence = MockLLM._classify_intent(text)
            return schema(intent=intent, confidence=confidence)  # type: ignore[return-value]
        # 工单抽取
        if schema is TicketExtraction:
            return schema(
                category=MockLLM._classify_ticket_category(text),
                priority="medium",
                impact="个人",
                summary=text[:200] or "未提供具体描述",
                missing_fields=[],
            )  # type: ignore[return-value]
        # 驳回摘要
        if schema is RejectSummary:
            return schema(
                summary="审批人驳回了您的申请，请根据以下提示补充材料后重新提交。",
                fix_hints=["补充必要的附件或说明"],
            )  # type: ignore[return-value]
        # 兜底：用字段默认值构造
        return schema()  # type: ignore[call-arg]

    @staticmethod
    def _last_user_text(messages: list[dict]) -> str:
        """取最后一条 user 消息文本。

        Args:
            messages: 消息列表。

        Returns:
            str: 用户消息内容，无则空串。
        """
        for m in reversed(messages):
            if m.get("role") == "user":
                return str(m.get("content", ""))
        return ""

    @staticmethod
    def _classify_intent(text: str) -> tuple[str, float]:
        """按关键词确定意图与置信度（FAQ 疑问词优先）。

        Args:
            text: 用户输入。

        Returns:
            tuple[str, float]: (意图, 置信度)。
        """
        # FAQ 疑问词优先判断，避免“请假流程是什么”被误判为请假申请
        for intent, keywords in _INTENT_KEYWORDS.items():
            if any(k in text for k in keywords):
                return intent, 0.95
        return "unknown", 0.1

    @staticmethod
    def _classify_ticket_category(text: str) -> str:
        """按关键词判断工单类别。

        Args:
            text: 用户输入。

        Returns:
            str: 工单类别。
        """
        if any(k in text for k in ["账号", "密码", "登录", "权限"]):
            return "账号权限"
        if any(k in text for k in ["设备", "电脑", "网络", "打印机", "故障"]):
            return "IT设备"
        if any(k in text for k in ["请假", "薪资", "考勤", "入职"]):
            return "HR事务"
        return "其他"
