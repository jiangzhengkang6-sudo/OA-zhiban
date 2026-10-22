"""
OA 智能体管理系统 - FAQ 问答子图。

定义问答闭环：权限过滤检索 -> (命中且置信度足够: 生成带来源回答 | 否则: 转人工兜底)。
未命中时由 FAQ 子图创建人工交接，返回 next_action=human。
"""

from langgraph.graph import END, START, StateGraph

from .nodes import faq_nodes
from .state import FaqState


def _after_retrieve(state: FaqState) -> str:
    """检索后的条件分支。

    Args:
        state: 子图状态。

    Returns:
        str: 下一节点名（answer/human）。
    """
    return "answer" if state.get("next_action") == "answer" else "human"


def _entry(state: FaqState) -> str:
    return "human" if state.get("intent") == "human" else "retrieve"


def build_faq_graph() -> StateGraph:
    """构建 FAQ 问答子图（未编译）。

    Returns:
        StateGraph: FAQ 子图构建器。
    """
    g = StateGraph(FaqState)
    g.add_node("faq_retrieve", faq_nodes.faq_retrieve)
    g.add_node("faq_answer", faq_nodes.faq_answer)
    g.add_node("human", faq_nodes.faq_to_human)

    g.add_conditional_edges(START, _entry, {"retrieve": "faq_retrieve", "human": "human"})
    g.add_conditional_edges("faq_retrieve", _after_retrieve, {
        "answer": "faq_answer",
        "human": "human",
    })
    g.add_edge("faq_answer", END)
    g.add_edge("human", END)
    return g
