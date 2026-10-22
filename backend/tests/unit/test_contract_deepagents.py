import pytest
from app.services.contract_deepagents import analyze_long_contract, ContractToolGate
from app.services.contract_parser import parse_text
from app.services import contract_deepagents as module
from types import SimpleNamespace
from langchain_core.messages import AIMessage


@pytest.mark.asyncio
async def test_real_deepagents_mock_plan_reads_all_blocks_and_returns_grounded_result():
    parsed = parse_text('付款条款：30日付款。\n' * 1200)
    result = await analyze_long_contract(parsed)
    assert result['engine'] == 'deepagents'
    assert result['planned']
    assert result['blocks_read'] == list(range(result['blocks']))
    assert result['model_calls'] <= 22
    assert result['provider'] == 'mock'


@pytest.mark.asyncio
async def test_forbidden_tool_denied_before_handler():
    class Request:
        tool_call = {'name':'execute','args':{'command':'dir'}, 'id':'x'}
    async def handler(request):
        pytest.fail('forbidden handler executed')
    with pytest.raises(ValueError, match='工具'):
        await ContractToolGate().awrap_tool_call(Request(), handler)


@pytest.mark.asyncio
async def test_model_call_budget_rejects_before_provider_request():
    model = module.ContractChatModel(provider='ark', calls=22)
    with pytest.raises(ValueError, match='预算'):
        await model._agenerate([])
    assert model.usage == []


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['missing_reads', 'too_many_reads', 'forged_quote', 'output_count'])
async def test_deepagents_rejects_incomplete_or_unbounded_output(monkeypatch, failure):
    parsed = parse_text('付款条款：30日付款。')
    class FakeAgent:
        def __init__(self, reader):
            self.reader = reader
        async def ainvoke(self, *args, **kwargs):
            if failure != 'missing_reads':
                for _ in range(21 if failure == 'too_many_reads' else 1):
                    await self.reader.ainvoke({'block_index': 0})
            observations = []
            if failure == 'forged_quote':
                observations = [{'paragraph': 1, 'quote': 'fabricated', 'suggestion': 'review'}]
            elif failure == 'output_count':
                observations = [{}] * 51
            import json
            return {'messages': [AIMessage(content=json.dumps({'observations': observations}))],
                'todos': [{'content': 'Review', 'status': 'in_progress'}]}
    def factory(**kwargs):
        return FakeAgent(kwargs['tools'][0])
    monkeypatch.setattr(module, 'create_deep_agent', factory)
    with pytest.raises(ValueError):
        await analyze_long_contract(parsed)


@pytest.mark.asyncio
async def test_tool_gate_hides_ambient_tools_from_model():
    request = SimpleNamespace(tools=[SimpleNamespace(name=name) for name in
        ['write_todos', 'read_contract_block', 'execute', 'task', 'read_file']])
    request.override = lambda **kwargs: SimpleNamespace(**kwargs)
    async def handler(filtered):
        return [tool.name for tool in filtered.tools]
    assert await ContractToolGate().awrap_model_call(request, handler) == ['write_todos', 'read_contract_block']
