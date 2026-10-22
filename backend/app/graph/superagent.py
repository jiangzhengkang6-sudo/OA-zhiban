"""
OA 智能体管理系统 - SuperAgent 顶层路由图。

负责意图识别与子图路由：加载上下文（含开关降级）-> 意图分类 -> 按意图路由到
请假/FAQ/工单子图。FAQ 未命中交由人工队列；所有路径收尾写审计。
"""

from langgraph.graph import END, START, StateGraph

from .faq_graph import build_faq_graph
from .leave_graph import build_leave_graph
from .nodes import common
from .state import AgentState
from .ticket_graph import build_ticket_graph
from .meeting_graph import build_meeting_graph, review_meeting


async def dedicated_workbench(state):
    return {"next_action": "paused", "error": {"code": "42201", "msg": "请通过对应业务工作台执行命令"}}


def _after_load(state: AgentState) -> str:
    """加载上下文后的条件分支（降级/继续）。

    Args:
        state: 图状态。

    Returns:
        str: 下一节点名。
    """
    if state.get("next_action") in ("degraded", "paused"):
        return "degrade"
    return "classify"


def _after_classify(state: AgentState) -> str:
    """意图分类后的条件分支。

    Args:
        state: 图状态。

    Returns:
        str: 子图节点名。
    """
    # The selected workflow is authoritative; classification cannot silently
    # turn a knowledge question into a ticket creation request.
    scene = state.get("scene")
    if scene in {"faq", "ticket", "leave"}:
        return scene
    intent = state.get("intent", "human")
    if intent == "leave":
        return "leave"
    if intent == "faq":
        return "faq"
    return "ticket"


def _after_faq(state: AgentState) -> str:
    """FAQ 子图后的条件分支（未命中由 FAQ 自身转人工）。

    Args:
        state: 图状态。

    Returns:
        str: 下一节点名。
    """
    return "audit_tail"


def build_superagent() -> StateGraph:
    """构建 SuperAgent 顶层图（未编译，由 GraphRuntime.compile 接入 Checkpointer）。

    Returns:
        StateGraph: 顶层图构建器。
    """
    g = StateGraph(AgentState)

    # 公共节点
    g.add_node("load_context", common.load_context)
    g.add_node("classify_intent", common.classify_intent)
    g.add_node("degrade", common.degrade)
    g.add_node("audit_tail", common.audit_tail)
    g.add_node("dedicated_workbench", dedicated_workbench)

    # 业务子图（作为节点，各自独立 StateGraph）
    g.add_node("leave", build_leave_graph().compile())
    g.add_node("faq", build_faq_graph().compile())
    g.add_node("ticket", build_ticket_graph().compile())
    g.add_node("meeting", build_meeting_graph().compile())
    g.add_node("meeting_review", review_meeting)

    g.add_conditional_edges(START, lambda state: "dedicated_workbench" if state.get("scene") in
        {"work_task", "report", "contract", "document", "email"} else
        "meeting" if state.get("scene") == "meeting" else "load_context",
        {"meeting": "meeting", "load_context": "load_context", "dedicated_workbench": "dedicated_workbench"})
    g.add_edge("dedicated_workbench", END)
    g.add_edge("meeting", "meeting_review")
    g.add_conditional_edges("meeting_review", lambda state: "meeting" if state.get("next_action") == "generate" else "end",
                            {"meeting": "meeting", "end": END})
    g.add_conditional_edges("load_context", _after_load, {
        "degrade": "degrade",
        "classify": "classify_intent",
    })
    g.add_conditional_edges("classify_intent", _after_classify, {
        "leave": "leave",
        "faq": "faq",
        "ticket": "ticket",
    })
    g.add_conditional_edges("faq", _after_faq, {
        "audit_tail": "audit_tail",
    })
    g.add_edge("leave", "audit_tail")
    g.add_edge("ticket", "audit_tail")
    g.add_edge("degrade", END)
    g.add_edge("audit_tail", END)

    return g
