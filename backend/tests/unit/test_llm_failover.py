"""Provider routing is verified offline, including tool calls and failure limits."""
import json

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.llm.base import LLMFactory
from app.llm.compatible import ProviderUnavailable


class Draft(BaseModel):
    summary: str


@pytest.fixture
def configure(monkeypatch):
    for name, value in {
        "LLM_PROVIDER": "deepseek", "LLM_FALLBACK_PROVIDER": "ark",
        "EMBEDDING_PROVIDER": "mock", "DEEPSEEK_API_KEY": "test-primary-secret",
        "DEEPSEEK_CHAT_MODEL": "deepseek-flash", "ARK_API_KEY": "test-fallback-secret",
        "ARK_CHAT_MODEL": "test-doubao-endpoint",
        "ARK_THINKING_TYPE": "default",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    original = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
            **{**kwargs, "transport": httpx.MockTransport(handler)}))

    yield install
    get_settings.cache_clear()


def response(content='{"summary":"ok"}', **extra):
    return httpx.Response(200, json={"choices": [{"message": {"content": content},
        "finish_reason": "stop"}], "usage": {"prompt_tokens": 12, "completion_tokens": 4,
        "total_tokens": 16}, **extra})


@pytest.mark.asyncio
async def test_primary_structured_success_and_embeddings_are_independent(configure):
    requests = []

    def handler(request):
        requests.append(request)
        return response()

    configure(handler)
    client = LLMFactory.get_llm()
    assert (await client.structured([], Draft, max_tokens=2048)).summary == "ok"
    body = json.loads(requests[0].content)
    assert len(requests) == 1
    assert body["model"] == "deepseek-flash"
    assert body["thinking"] == {"type": "disabled"}
    assert body["max_tokens"] == 2048
    assert body["response_format"] == {"type": "json_object"}
    assert client.last_attempts[0]["provider"] == "deepseek"
    assert client.last_usage["total_tokens"] == 16
    from app.llm.embedding import MockEmbedding
    assert isinstance(LLMFactory.get_embedding(), MockEmbedding)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [429, 500, 502, 503, "timeout", "connect"])
async def test_recoverable_failure_uses_doubao_once(configure, failure):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "api.deepseek.com":
            if failure == "timeout":
                raise httpx.ReadTimeout("private prompt", request=request)
            if failure == "connect":
                raise httpx.ConnectError("private prompt", request=request)
            return httpx.Response(failure, text="private prompt")
        return response()

    configure(handler)
    client = LLMFactory.get_llm()
    assert (await client.structured([], Draft, model="primary-only-override")).summary == "ok"
    assert len(requests) == 2
    assert json.loads(requests[1].content)["model"] == "test-doubao-endpoint"
    assert "thinking" not in json.loads(requests[1].content)
    assert requests[1].headers["Authorization"] == "Bearer test-fallback-secret"
    assert [item["provider"] for item in client.last_attempts] == ["deepseek", "ark"]
    assert "private prompt" not in str(client.last_attempts)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_permanent_errors_do_not_fallback_or_expose_response(configure, status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="private prompt test-primary-secret")

    configure(handler)
    with pytest.raises(RuntimeError) as caught:
        await LLMFactory.get_llm().chat([])
    assert len(requests) == 1
    assert "private prompt" not in str(caught.value)
    assert "test-primary-secret" not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["not json", '{"other":"private text"}', ""])
async def test_invalid_output_is_rejected_without_retry(configure, content):
    requests = []

    def handler(request):
        requests.append(request)
        return response(content)

    configure(handler)
    client = LLMFactory.get_llm()
    with pytest.raises(RuntimeError, match="output"):
        await client.structured([], Draft)
    assert len(requests) == 1
    assert client.last_usage["total_tokens"] == 16


@pytest.mark.asyncio
async def test_both_providers_fail_without_mock_success(configure):
    calls = []
    configure(lambda request: calls.append(request) or httpx.Response(503, text="private"))
    client = LLMFactory.get_llm()
    with pytest.raises(ProviderUnavailable, match="configured text models are unavailable"):
        await client.chat([])
    assert len(calls) == 2
    assert all(attempt["status"] == "unavailable" for attempt in client.last_attempts)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["default", "disabled", "enabled", "auto"])
async def test_ark_thinking_mode_is_explicitly_configurable(configure, monkeypatch, mode):
    monkeypatch.setenv("LLM_PROVIDER", "ark")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "none")
    monkeypatch.setenv("ARK_THINKING_TYPE", mode)
    get_settings.cache_clear()
    requests = []
    configure(lambda request: requests.append(request) or response())
    assert (await LLMFactory.get_llm().structured([], Draft)).summary == "ok"
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    if mode == "default":
        assert "thinking" not in body
    else:
        assert body["thinking"] == {"type": mode}


@pytest.mark.asyncio
async def test_structured_timeout_override_covers_http_and_total_deadline(configure, monkeypatch):
    import asyncio

    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "none")
    get_settings.cache_clear()
    requests = []

    async def handler(request):
        requests.append(request)
        await asyncio.sleep(0.03)
        return response()

    configure(handler)
    client = LLMFactory.get_llm()
    assert (await client.structured([], Draft, timeout_seconds=0.2)).summary == "ok"
    assert requests[0].extensions["timeout"]["read"] == 0.2
    with pytest.raises(ProviderUnavailable):
        await client.structured([], Draft)


@pytest.mark.asyncio
async def test_meeting_generation_uses_its_own_timeout(configure, monkeypatch):
    from app.services.meeting_generator import generate

    monkeypatch.setenv("MEETING_LLM_TIMEOUT_SECONDS", "25")
    get_settings.cache_clear()
    requests = []
    configure(lambda request: requests.append(request) or response(
        '{"summary":"meeting","source_refs":["s1"]}'))
    await generate([{"segment_id": "s1", "text": "议题：验收。"}])
    assert requests[0].extensions["timeout"]["read"] == 25
    assert json.loads(requests[0].content)["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_tool_fallback_preserves_tools_and_physical_request_budget(configure):
    requests = []
    tools = [{"type": "function", "function": {"name": "read_contract_block",
        "parameters": {"type": "object", "properties": {}}}}]

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
            "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {
                "name": "read_contract_block", "arguments": '{"block_index":0}'}}]}}]})

    configure(handler)
    client = LLMFactory.get_llm()
    remaining = 1

    def budget():
        nonlocal remaining
        if remaining == 0:
            raise ValueError("request budget exhausted")
        remaining -= 1

    with pytest.raises(ValueError, match="budget"):
        await client.complete([], tools=tools, before_request=budget)
    assert len(requests) == 1
    client = LLMFactory.get_llm()
    data = await client.complete([], tools=tools)
    assert data["choices"][0]["message"]["tool_calls"]
    assert json.loads(requests[-1].content)["tools"] == tools


@pytest.mark.asyncio
async def test_missing_primary_credentials_never_fallback(configure, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    get_settings.cache_clear()
    configure(lambda request: pytest.fail("network request without credentials"))
    with pytest.raises(RuntimeError, match="configuration"):
        await LLMFactory.get_llm().chat([])


def test_unknown_provider_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_provider="typo")


@pytest.mark.asyncio
async def test_disabled_fallback_and_model_override_stays_on_primary(configure, monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "none")
    get_settings.cache_clear()
    requests = []
    configure(lambda request: requests.append(request) or httpx.Response(503))
    with pytest.raises(RuntimeError):
        await LLMFactory.get_llm().chat([], model="custom-primary")
    assert len(requests) == 1
    assert json.loads(requests[0].content)["model"] == "custom-primary"


@pytest.mark.asyncio
async def test_contract_tool_messages_and_fallback_count_as_two_requests(configure):
    from app.services.contract_deepagents import ContractChatModel
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) % 2:
            return httpx.Response(503)
        return response('{"observations":[]}')

    configure(handler)
    model = ContractChatModel(provider="deepseek")
    await model._agenerate([HumanMessage(content="review"), AIMessage(content="", tool_calls=[{
        "name": "read_contract_block", "args": {"block_index": 0}, "id": "call_1"}]),
        ToolMessage(content="authorized block", tool_call_id="call_1")], tools=[])
    assert model.calls == 2
    assert [item["provider"] for item in model.usage] == ["deepseek", "ark"]
    body = json.loads(requests[1].content)
    assert body["messages"][-1]["tool_call_id"] == "call_1"
    assert json.loads(body["messages"][-2]["tool_calls"][0]["function"]["arguments"]) == {"block_index": 0}
    model = ContractChatModel(provider="deepseek", calls=21)
    with pytest.raises(ValueError, match="预算"):
        await model._agenerate([])
    assert model.calls == 22
    assert len(requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("forged", [False, True])
async def test_meeting_uses_primary_and_rejects_unknown_evidence(configure, forged):
    from app.services import meeting_generator
    segments = [{"segment_id": "segment:1", "text": "Submit report"}]
    draft = {"summary": "Submit report", "source_refs": ["segment:1"],
        "action_items": [{"title": "Submit report", "source_refs": ["forged" if forged else "segment:1"],
            "needs_confirmation": False}]}
    requests = []
    configure(lambda request: requests.append(request) or response(json.dumps(draft)))
    if forged:
        with pytest.raises(ValueError, match="reference"):
            await meeting_generator.generate(segments)
    else:
        result = await meeting_generator.generate(segments)
        assert result["action_items"][0]["needs_confirmation"] is True
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_real_deepagents_engine_with_primary_failure_and_doubao_tools(configure):
    from app.services.contract_deepagents import analyze_long_contract
    from app.services.contract_parser import parse_text

    def tool_response(name, args):
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
            "content": None, "tool_calls": [{"id": name, "type": "function", "function": {
                "name": name, "arguments": json.dumps(args)}}]}}], "usage": {"total_tokens": 10}})

    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "api.deepseek.com":
            return httpx.Response(503)
        body = json.loads(request.content)
        tool_ids = [m["tool_call_id"] for m in body["messages"] if m["role"] == "tool"]
        if "write_todos" not in tool_ids:
            return tool_response("write_todos", {"todos": [{"content": "Review", "status": "in_progress"}]})
        if "read_contract_block" not in tool_ids:
            return tool_response("read_contract_block", {"block_index": 0})
        return response('{"observations":[]}')

    configure(handler)
    result = await analyze_long_contract(parse_text("Payment is due."))
    assert result["engine"] == "deepagents"
    assert result["blocks_read"] == [0]
    assert result["model_calls"] == len(requests) == 6
    assert [u["provider"] for u in result["usage"]] == ["deepseek", "ark"] * 3


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["length", "content_filter", "aborted"])
async def test_truncated_or_filtered_output_is_not_accepted(configure, finish_reason):
    configure(lambda request: response(choices=[{"message": {"content": '{"summary":"ok"}'},
                                                "finish_reason": finish_reason}]))
    client = LLMFactory.get_llm()
    with pytest.raises(RuntimeError, match="output"):
        await client.structured([], Draft)
    assert len(client.last_attempts) == 1
    assert client.last_attempts[0]["status"] == "invalid_output"


@pytest.mark.asyncio
async def test_total_request_deadline_allows_fallback(configure, monkeypatch):
    import asyncio
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "0.03")
    get_settings.cache_clear()

    async def handler(request):
        if request.url.host == "api.deepseek.com":
            await asyncio.sleep(1)
        return response("ok")

    configure(handler)
    client = LLMFactory.get_llm()
    assert await client.chat([]) == "ok"
    assert [a["status"] for a in client.last_attempts] == ["unavailable", "success"]


@pytest.mark.asyncio
async def test_usage_rows_follow_actual_providers_and_unknown_usage_stays_unknown():
    from types import SimpleNamespace
    from app.services.runtime_trace_service import record_model_attempts
    rows = []
    await record_model_attempts(SimpleNamespace(add=rows.append), tenant_id="tenant", trace_id="trace",
        provider="deepseek", model_name="primary", usage={"attempts": [
            {"provider": "deepseek", "model": "primary", "usage": {}},
            {"provider": "ark", "model": "fallback", "usage": {"total_tokens": 16}}]})
    assert [(r.provider, r.model_name, r.total_tokens, r.usage_missing) for r in rows] == [
        ("deepseek", "primary", None, True), ("ark", "fallback", 16, False)]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["work_task", "report", "document", "email"])
async def test_business_generators_use_fallback_and_keep_output_caps(configure, kind):
    usage, requests = {}, []
    source = {"ref": "source:1", "content": "Submit report"}
    drafts = {
        "work_task": {"candidates": [{"candidate_id": "model-id", "title": "Submit report",
            "source_refs": [source["ref"]]}]},
        "report": {"summary": "Data requires review.", "metric_refs": ["ticket_volume"]},
        "document": {"body": "# Report\n## Details\nSubmit report", "source_refs": [source["ref"]]},
        "email": {"category": "work", "priority": "normal", "summary": "Submit report",
            "reply_subject": "Re: Report", "reply_body": "Received.", "source_refs": [source["ref"]]},
    }

    def handler(request):
        requests.append(request)
        return httpx.Response(503) if len(requests) == 1 else response(json.dumps(drafts[kind]))

    configure(handler)
    if kind == "work_task":
        from app.services.work_task_generator import generate
        result = await generate(source, usage)
        assert result[0]["assignee_id"] is None and result[0]["candidate_id"] != "model-id"
    elif kind == "report":
        from app.services.report_generator import generate
        await generate({"metrics": [{"metric_id": "ticket_volume", "current": 2, "previous": 1}]}, usage=usage)
    elif kind == "document":
        from app.services.document_generator import generate
        from app.schemas.document import DocumentInput
        from app.services.document_templates import TEMPLATES
        await generate(DocumentInput(template_id="notice", subject="Report", recipient="Team",
            key_points="Submit report", distribution="Team", idempotency_key="draft"),
            TEMPLATES["notice"], [source])
    else:
        from app.services.email_generator import generate
        from app.schemas.email import EmailInput
        await generate(EmailInput(subject="Report", sender="sender", recipients=["recipient"],
            body="Submit report", idempotency_key="draft"), [source])
    assert len(requests) == 2
    assert json.loads(requests[-1].content)["max_tokens"] == (2048 if kind in {"work_task", "report"} else 4096)
    if kind in {"work_task", "report"}:
        assert [a["provider"] for a in usage["attempts"]] == ["deepseek", "ark"]


@pytest.mark.asyncio
async def test_faq_deepseek_branch_generates_answer_from_evidence(configure, monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.graph.nodes import faq_nodes
    requests = []

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(faq_nodes, "async_session_factory", session)
    monkeypatch.setattr(faq_nodes.audit_service, "audit", AsyncMock())
    configure(lambda request: requests.append(request) or response("Generated answer"))
    result = await faq_nodes.faq_answer({"question": "What is the policy?",
        "faq_chunks": [{"content": "Authorized evidence", "similarity": 0.9, "title": "Policy"}]})
    assert result["answer"]["answer"] == "Generated answer"
    assert "Authorized evidence" in json.loads(requests[0].content)["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_meeting_graph_runs_real_generation_with_stable_node_name(configure):
    from app.graph.meeting_graph import build_meeting_graph

    def handler(request):
        segments = json.loads(json.loads(request.content)["messages"][-1]["content"])
        return response(json.dumps({"summary": "Review", "source_refs": [segments[0]["segment_id"]]}))

    configure(handler)
    result = await build_meeting_graph().compile().ainvoke({"content": "Topic: Review."})
    assert result["meeting_status"] == "DRAFT_READY"
    assert result["draft"]["summary"] == "Review"


@pytest.mark.asyncio
async def test_tool_arguments_cannot_bypass_response_size_budget(configure):
    configure(lambda request: response(choices=[{"message": {"tool_calls": [{"function": {
        "name": "read_contract_block", "arguments": "x" * 40000}}]}, "finish_reason": "tool_calls"}]))
    with pytest.raises(RuntimeError, match="output"):
        await LLMFactory.get_llm().complete([], tools=[{"type": "function", "function": {"name": "read_contract_block"}}])
