"""
OA 智能体管理系统 - 请假审批子图。

定义请假审批闭环的状态图：预检 -> (失败: NEEDS_FIX / 通过: 路由) -> 审批门(HITL) ->
(批准: 执行写操作+通知 | 驳回: 摘要+通知 | 编辑: 合并回预检回环)。
写工具严格在 HITL 通过后调用且幂等。
"""

from langgraph.graph import END, START, StateGraph

from .nodes import leave_nodes
from .state import LeaveState


def _after_precheck(state: LeaveState) -> str:
    """预检后的条件分支。

    Args:
        state: 子图状态。

    Returns:
        str: 下一节点名（route/needs_fix/paused）。
    """
    na = state.get("next_action", "paused")
    if na == "paused":
        return "paused"
    if na == "needs_fix":
        return "needs_fix"
    return "route"


def _after_gate(state: LeaveState) -> str:
    """审批门后的条件分支。

    Args:
        state: 子图状态。

    Returns:
        str: 下一节点名（approve/edit/reject）。
    """
    decision = state.get("human_decision") or {}
    if decision.get("result_status") == "waiting_human" and decision.get("action") == "approve":
        return "approval_gate"
    return decision.get("action", "reject")


def _after_route(state: LeaveState) -> str:
    """路由失败时直接结束，禁止进入人工审批门。"""
    return "paused" if state.get("next_action") == "paused" else "approval_gate"


def build_leave_graph() -> StateGraph:
    """构建请假审批子图（未编译）。

    Returns:
        StateGraph: 请假子图构建器。
    """
    from ..core.config import get_settings
    if get_settings().oa_provider == 'builtin':
        from ..services.oa_leave_graph_service import build_graph
        return build_graph()
    g = StateGraph(LeaveState)

    g.add_node("precheck", leave_nodes.precheck)
    g.add_node("route", leave_nodes.route)
    g.add_node("approval_gate", leave_nodes.approval_gate)
    g.add_node("execute_approval", leave_nodes.execute_approval)
    g.add_node("reject_summary", leave_nodes.reject_summary)
    g.add_node("merge_edited", leave_nodes.merge_edited)
    g.add_node("notify", leave_nodes.notify_outcome)
    # 终态占位（LangGraph 需要显式节点名，这里用 END 标记语义）
    g.add_node("needs_fix", leave_nodes.needs_fix)
    g.add_node("paused", leave_nodes.paused)

    g.add_edge(START, "precheck")
    g.add_conditional_edges("precheck", _after_precheck, {
        "route": "route",
        "needs_fix": "needs_fix",
        "paused": "paused",
    })
    g.add_conditional_edges("route", _after_route, {
        "approval_gate": "approval_gate",
        "paused": "paused",
    })
    g.add_conditional_edges("approval_gate", _after_gate, {
        "approval_gate": "approval_gate",
        "approve": "execute_approval",
        "edit": "merge_edited",
        "reject": "reject_summary",
    })
    g.add_edge("execute_approval", "notify")
    g.add_edge("reject_summary", "notify")
    g.add_edge("merge_edited", "precheck")
    g.add_edge("notify", END)
    g.add_edge("needs_fix", END)
    g.add_edge("paused", END)

    return g
