"""Bounded report query and evidence summary nodes under service-owned review."""
import asyncio
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from ..core.context import CurrentUser
from ..services import report_generator
from ..tools.report_tools import run_registered_report_query


class ReportState(TypedDict, total=False):
    actor: CurrentUser
    plan: dict
    snapshot: dict | None
    draft: dict
    failed_phase: str | None
    model_usage: dict


async def query_data(state):
    if state.get("snapshot") is not None:
        return {"failed_phase": None}
    try:
        snapshot = await asyncio.wait_for(run_registered_report_query(state["actor"], state["plan"]), 20)
        return {"snapshot": snapshot, "failed_phase": None}
    except Exception:
        return {"failed_phase": "QUERY_FAILED"}


async def summarize_data(state):
    usage = {}
    try:
        draft = await asyncio.wait_for(report_generator.generate(state["snapshot"], usage=usage), 25)
        return {"draft": draft.model_dump(mode="json"), "failed_phase": None, "model_usage": usage}
    except Exception:
        return {"failed_phase": "MODEL_FAILED", "model_usage": usage}


def build_report_graph():
    graph = StateGraph(ReportState)
    graph.add_node("query_data", query_data)
    graph.add_node("summarize_data", summarize_data)
    graph.add_edge(START, "query_data")
    graph.add_conditional_edges("query_data", lambda state: "failed" if state.get("failed_phase") else "summary",
        {"failed": END, "summary": "summarize_data"})
    graph.add_edge("summarize_data", END)
    return graph


report_graph = build_report_graph().compile()
