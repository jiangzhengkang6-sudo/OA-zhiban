"""Dedicated business scenes cannot inherit generic chat write tools."""
import pytest
from unittest.mock import AsyncMock
from app.graph.superagent import build_superagent
from app.graph.nodes import common
from app.tools.registry import is_tool_allowed


@pytest.mark.asyncio
@pytest.mark.parametrize('scene', ['work_task', 'report', 'contract'])
async def test_superagent_routes_p3_to_dedicated_workbench(monkeypatch, scene):
    load = AsyncMock(side_effect=AssertionError('generic graph entered'))
    monkeypatch.setattr(common, 'load_context', load)
    result = await build_superagent().compile().ainvoke({'scene': scene})
    assert result['next_action'] == 'paused'
    assert result['error']['code'] == '42201'
    load.assert_not_called()
    for tool in ['notify_user', 'create_or_merge_ticket', 'create_or_update_oa_approval', 'execute', 'task']:
        assert not is_tool_allowed(scene, tool)
