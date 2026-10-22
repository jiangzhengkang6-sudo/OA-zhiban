"""
OA 智能体管理系统 - 请假审批闭环集成测试。

依赖真实 PostgreSQL（docker）与 LangGraph Checkpointer，验证预检 -> 路由 -> HITL
中断 -> 审批恢复的完整闭环，对应 AC-MVP-01 至 AC-MVP-07。
"""

import pytest
from uuid import UUID, uuid4

from app.graph.graph_service import extract_interrupt, runtime


def _tid() -> UUID:
    """生成随机 thread_id。"""
    return uuid4()


@pytest.mark.asyncio
async def test_leave_approve_flow(graph_ready):
    """材料齐全 -> 预检通过 -> 中断 -> 批准 -> approved。"""
    tid = _tid()
    result = await runtime.invoke(tid, {
        "thread_id": str(tid), "user_id": "u_emp_001", "tenant_id": "t_001",
        "scene": "leave", "business_id": "LV-OK-001", "trace_id": "test-1",
        "messages": [{"role": "user", "content": "提交请假申请"}],
    })
    snapshot = await runtime.get_state(tid)
    interrupt = extract_interrupt(snapshot)
    assert interrupt is not None, "应产生审批中断"
    # 预检结果通过 interrupt payload 暴露
    assert interrupt[1].get("precheck", {}).get("passed") is True

    result2 = await runtime.resume(tid, {
        "action": "approve", "comment": "同意", "actor_id": "u_mgr_001", "idempotency_key": f"first-{tid}",
    })
    snapshot2 = await runtime.get_state(tid)
    assert extract_interrupt(snapshot2) is not None
    result3 = await runtime.resume(tid, {
        "action": "approve", "comment": "二级同意", "actor_id": "u_mgr_002", "idempotency_key": f"second-{tid}",
    })
    assert result3.get("next_action") == "approved"


@pytest.mark.asyncio
async def test_leave_needs_fix(graph_ready):
    """病假缺附件 -> 预检失败 -> needs_fix。"""
    tid = _tid()
    result = await runtime.invoke(tid, {
        "thread_id": str(tid), "user_id": "u_emp_001", "tenant_id": "t_001",
        "scene": "leave", "business_id": "LV-NOATT-001", "trace_id": "test-2",
        "messages": [{"role": "user", "content": "提交请假申请"}],
    })
    assert result.get("precheck", {}).get("passed") is False
    assert result.get("next_action") == "needs_fix"

    snapshot = await runtime.get_state(tid)
    assert extract_interrupt(snapshot) is None, "预检失败不应产生审批中断"


@pytest.mark.asyncio
async def test_leave_reject_flow(graph_ready):
    """审批人驳回 -> rejected 并生成驳回摘要。"""
    tid = _tid()
    await runtime.invoke(tid, {
        "thread_id": str(tid), "user_id": "u_emp_001", "tenant_id": "t_001",
        "scene": "leave", "business_id": "LV-OK-001", "trace_id": "test-3",
        "messages": [{"role": "user", "content": "提交请假申请"}],
    })
    snapshot = await runtime.get_state(tid)
    interrupt = extract_interrupt(snapshot)
    assert interrupt is not None

    result = await runtime.resume(tid, {
        "action": "reject", "comment": "材料不齐", "actor_id": "u_mgr_001", "idempotency_key": f"reject-{tid}",
    })
    assert result.get("next_action") == "rejected"


@pytest.mark.asyncio
async def test_balance_dependency_failure_does_not_create_approval(graph_ready, monkeypatch):
    from app.adapters.factory import get_adapter
    from app.db.session import async_session_factory
    from app.services.approval_service import get_instance
    tid = _tid()
    def fail_balance(*args):
        raise TimeoutError("余额查询超时")
    monkeypatch.setattr(get_adapter(), "get_leave_balance", fail_balance)
    result = await runtime.invoke(tid, {
        "thread_id": str(tid), "user_id": "u_emp_001", "tenant_id": "t_001",
        "scene": "leave", "business_id": "LV-OK-001", "trace_id": "balance-fail",
        "messages": [{"role": "user", "content": "提交请假申请"}],
    })
    assert result["next_action"] == "paused"
    async with async_session_factory() as db:
        assert await get_instance(db, tid) is None


@pytest.mark.asyncio
async def test_unexpected_route_failure_pauses_without_approval(graph_ready, monkeypatch):
    from app.adapters.factory import get_adapter
    from app.db.session import async_session_factory
    from app.services.approval_service import get_instance
    tid = _tid()
    def fail_route(*args):
        raise ValueError("组织路由不可判定")
    monkeypatch.setattr(get_adapter(), "get_approval_route", fail_route)
    result = await runtime.invoke(tid, {
        "thread_id": str(tid), "user_id": "u_emp_001", "tenant_id": "t_001",
        "scene": "leave", "business_id": "LV-OK-001", "trace_id": "route-fail",
        "messages": [{"role": "user", "content": "提交请假申请"}],
    })
    assert result["next_action"] == "paused"
    async with async_session_factory() as db:
        assert await get_instance(db, tid) is None
