import pytest
from app.graph import contract_graph as module
from app.services.contract_parser import parse_text


@pytest.mark.asyncio
async def test_retry_keeps_rule_snapshot_across_rule_deployment(monkeypatch):
    graph = module.build_contract_graph()
    state = {"parsed": parse_text("付款条款：30日付款。" + "\n保密条款。" * 1600)}
    async def fail(parsed):
        raise ValueError("model unavailable")
    monkeypatch.setattr(module, "analyze_long_contract", fail)
    with pytest.raises(ValueError):
        async for event in graph.astream(state, stream_mode="updates"):
            state.update(next(iter(event.values())))
    assert state["node_trace"] == ["extract_clauses", "check_rules"]
    monkeypatch.setattr(module, "RULE_VERSION", "demo-2")
    async def succeed(parsed):
        return {"engine": "deepagents", "usage": [], "observations": []}
    monkeypatch.setattr(module, "analyze_long_contract", succeed)
    result = await module.build_contract_graph().ainvoke(state)
    assert result["draft"]["rule_version"] == "demo-1"
    assert {risk["rule_version"] for risk in result["draft"]["risks"]} == {"demo-1"}


@pytest.mark.asyncio
async def test_snapshot_is_fixed_before_rules_node(monkeypatch):
    graph = module.build_contract_graph()
    state = {"parsed": parse_text("付款条款：30日付款。")}
    stream = graph.astream(state, stream_mode="updates")
    state.update(next(iter((await anext(stream)).values())))
    await stream.aclose()
    monkeypatch.setattr(module, "RULE_VERSION", "demo-2")
    monkeypatch.setattr(module, "RULES", [("new", "new", ("new",))])
    result = await module.build_contract_graph().ainvoke(state)
    assert result["draft"]["rule_version"] == "demo-1"
    assert [risk["risk_id"] for risk in result["draft"]["risks"]] == ["payment", "breach", "termination", "dispute"]
