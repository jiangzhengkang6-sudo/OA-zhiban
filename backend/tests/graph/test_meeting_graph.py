import pytest

from app.graph.meeting_graph import build_meeting_graph


@pytest.mark.asyncio
async def test_meeting_graph_generates_cited_platform_draft():
    graph = build_meeting_graph().compile()
    result = await graph.ainvoke({"content": "议题已确认。下周跟进。"})

    assert result["meeting_status"] == "DRAFT_READY"
    assert result["draft"]["source_refs"]
    assert result["next_action"] == "review"


@pytest.mark.asyncio
async def test_meeting_failure_logs_safe_category_without_source_or_key(monkeypatch, caplog):
    from app.graph.meeting_graph import generate_mock_draft
    from app.services import meeting_generator
    from app.llm.compatible import ProviderUnavailable

    async def unavailable(segments):
        raise ProviderUnavailable("private meeting text secret-api-key")

    monkeypatch.setattr(meeting_generator, "generate", unavailable)
    with pytest.raises(RuntimeError, match="会议生成依赖暂不可用"):
        await generate_mock_draft({"segments": []})
    assert "kind=ProviderUnavailable" in caplog.text
    assert "private meeting text" not in caplog.text
    assert "secret-api-key" not in caplog.text


@pytest.mark.asyncio
async def test_superagent_meeting_bypasses_classifier_and_preserves_cited_fields(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from app.graph.superagent import build_superagent
    from app.graph.nodes import common
    from app.graph.graph_service import extract_interrupt
    from uuid import uuid4

    async def classify(*args):
        raise AssertionError("会议不得送入工单分类器")

    async def load(state):
        return {"policy": {"enabled": True, "thresholds": {}}}

    async def tail(state):
        return {}

    monkeypatch.setattr(common, "classify_intent", classify)
    monkeypatch.setattr(common, "load_context", load)
    monkeypatch.setattr(common, "audit_tail", tail)
    graph = build_superagent().compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": str(uuid4())}}
    await graph.ainvoke({
        "scene": "meeting", "user_id": "u_emp_001", "tenant_id": "t_001",
        "content": "议题：验收。决定：灰度发布。待办：完成验收。",
        "meeting_version": 1, "meeting_command_key": "generate-1",
    }, config=config)
    snapshot = await graph.aget_state(config)
    assert snapshot.values["draft"]["decisions"]
    assert snapshot.values["draft"]["action_items"]
    pending = extract_interrupt(snapshot)
    assert pending and pending[1]["type"] == "meeting_review"
    assert pending[1]["version"] == 1
    assert "draft" not in pending[1] and "content" not in pending[1]
