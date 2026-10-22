"""
OA 智能体管理系统 - 工单子图。

定义工单闭环：字段抽取 -> 用户确认（HITL）-> 创建/合并工单并转人工队列。
用户取消则结束，编辑则回抽取。转人工（human）意图复用同一子图。
"""

from langgraph.graph import END, START, StateGraph

from .nodes import ticket_nodes
from .state import TicketState


def _after_confirm(state: TicketState) -> str:
    """确认后的条件分支。

    Args:
        state: 子图状态。

    Returns:
        str: 下一节点名（confirm/cancel/edit）。
    """
    confirmation = state.get("confirmation") or {}
    action = confirmation.get("action", "cancel")
    if action == "edit":
        return "edit"
    if action == "confirm":
        return "confirm"
    return "cancel"


def _entry(state: TicketState) -> str:
    return "human" if state.get("intent") == "human" else "extract"


def build_ticket_graph() -> StateGraph:
    """构建工单子图（未编译）。

    Returns:
        StateGraph: 工单子图构建器。
    """
    g = StateGraph(TicketState)
    g.add_node("ticket_extract", ticket_nodes.ticket_extract)
    g.add_node("ticket_confirm", ticket_nodes.ticket_confirm)
    g.add_node("create_ticket", ticket_nodes.create_ticket)
    g.add_node("human", ticket_nodes.ticket_human)
    g.add_node("cancelled", ticket_nodes.ticket_cancelled)

    g.add_conditional_edges(START, _entry, {"extract": "ticket_extract", "human": "human"})
    g.add_edge("ticket_extract", "ticket_confirm")
    g.add_conditional_edges("ticket_confirm", _after_confirm, {
        "confirm": "create_ticket",
        "cancel": "cancelled",
        "edit": "ticket_extract",
    })
    g.add_edge("create_ticket", "human")
    g.add_edge("human", END)
    g.add_edge("cancelled", END)
    return g
