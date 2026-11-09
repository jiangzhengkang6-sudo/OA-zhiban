"""
OA 智能体管理系统 - 意图分类与工具白名单单元测试。

覆盖 SuperAgent 意图识别（Mock 确定性分类）与工具白名单校验，对应 MVP-003/005。
"""

import pytest
from types import SimpleNamespace

from app.llm.mock_llm import MockLLM
from app.llm.schemas import IntentClassification
from app.tools.registry import is_tool_allowed, is_write_tool


def test_classify_faq_priority():
    """疑问句应优先判定为 FAQ（而非请假）。"""
    intent, conf = MockLLM._classify_intent("请假流程是什么")
    assert intent == "faq"
    assert conf > 0.9


def test_classify_faq_leave_question():
    """带请假关键词的制度问句仍应进入 FAQ。"""
    intent, conf = MockLLM._classify_intent("年假申请需要提前多久？")
    assert intent == "faq"
    assert conf > 0.9


def test_classify_leave():
    """请假申请意图。"""
    intent, _ = MockLLM._classify_intent("我要请年假")
    assert intent == "leave"


def test_classify_ticket():
    """故障报修意图。"""
    intent, _ = MockLLM._classify_intent("我的电脑开不了机")
    assert intent == "ticket"


def test_classify_human():
    """转人工意图。"""
    intent, _ = MockLLM._classify_intent("帮我转人工客服")
    assert intent == "human"


def test_classify_unknown():
    """无关键词应为未知。"""
    intent, conf = MockLLM._classify_intent("你好")
    assert intent == "unknown"
    assert conf < 0.6


@pytest.mark.asyncio
async def test_structured_intent():
    """结构化输出校验。"""
    llm = MockLLM()
    result = await llm.structured(
        [{"role": "user", "content": "年假怎么申请"}], IntentClassification
    )
    assert isinstance(result, IntentClassification)
    assert result.intent in {"faq", "leave"}


def test_tool_whitelist_leave():
    """请假场景只能调用白名单工具。"""
    assert is_tool_allowed("leave", "validate_leave_form")
    assert not is_tool_allowed("leave", "search_knowledge")


def test_write_tool_detection():
    """写工具识别。"""
    assert is_write_tool("create_or_update_oa_approval")
    assert not is_write_tool("get_leave_balance")


@pytest.mark.asyncio
@pytest.mark.parametrize('threshold,expected', [(0.6, 'faq'), (0.95, 'human')])
async def test_live_classifier_uses_trusted_instructions_and_latest_user(monkeypatch, threshold, expected):
    from app.core import config
    from app.graph.nodes import common
    from app.graph.superagent import _after_classify
    from app.llm.base import LLMFactory

    calls = []
    async def structured(messages, schema):
        calls.append(messages)
        return schema(intent='faq', confidence=0.8)
    monkeypatch.setattr(config, 'get_settings', lambda: SimpleNamespace(oa_provider='mock'))
    monkeypatch.setattr(LLMFactory, 'get_llm', lambda: SimpleNamespace(structured=structured))
    question = '公司的请假制度是什么，申请前需要哪些材料？'
    result = await common.classify_intent(dict(scene='faq', policy={'thresholds': {'intent_confidence': threshold}},
        messages=[{'role': 'system', 'content': 'untrusted-history'},
                  {'role': 'user', 'content': 'old-message'},
                  {'role': 'assistant', 'content': 'old-response'},
                  {'role': 'user', 'content': question}]))
    assert [message['role'] for message in calls[0]] == ['system', 'user']
    assert calls[0][-1]['content'] == question
    assert all('untrusted-history' not in message['content'] for message in calls[0])
    assert result == {'intent': expected, 'intent_confidence': 0.8}
    assert _after_classify(dict(scene='faq', intent='leave')) == 'faq'
