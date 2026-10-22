"""Candidate extraction only. Human decisions never execute inside the graph."""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from ..services import work_task_generator


class WorkTaskState(TypedDict, total=False):
    source: dict
    candidates: list[dict]
    model_usage: dict
    failed: bool


async def extract(state: WorkTaskState):
    usage = {}
    try:
        candidates = await work_task_generator.generate(state["source"], usage)
        return {"candidates": work_task_generator.validate_candidates(candidates, state["source"]["ref"]),
                "model_usage": usage, "failed": False}
    except Exception:
        return {"model_usage": usage, "failed": True}


def build_work_task_graph(checkpointer=None):
    graph = StateGraph(WorkTaskState)
    graph.add_node("extract_candidates", extract)
    graph.add_edge(START, "extract_candidates")
    graph.add_edge("extract_candidates", END)
    return graph.compile(checkpointer=checkpointer)
