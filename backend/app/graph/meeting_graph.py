"""Meeting text graph with provider-independent human review."""

import logging

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..services.meeting_parser import MeetingParser
from ..services import meeting_generator
from ..services.authorization_service import require_business_identity
from ..core.context import CurrentUser
from ..core.context import get_trace_id
from ..core.errors import AppException
from ..core.enums import ErrorCode
from .state import MeetingState

logger = logging.getLogger("oa-agent")


async def parse_meeting(state: MeetingState) -> dict:
    await _authorize(state)
    segments = state.get("segments")
    if not segments:
        segments = [item.model_dump() for item in MeetingParser().parse(state.get("content", ""))]
    return {
        "segments": segments,
        "meeting_status": "PROCESSING",
        "next_action": "generate",
    }


async def generate_mock_draft(state: MeetingState) -> dict:
    await _authorize(state)
    segments = state.get("segments") or []
    try:
        draft = await meeting_generator.generate(segments)
    except Exception as exc:
        logger.warning("Meeting generation failed: kind=%s trace_id=%s",
                       type(exc).__name__, get_trace_id())
        # Checkpoint error messages must not contain provider prompts or raw text.
        raise RuntimeError("会议生成依赖暂不可用") from None
    return {
        "draft": draft,
        "meeting_status": "DRAFT_READY",
        "next_action": "review",
    }


async def _authorize(state):
    if state.get("user_id"):
        actor = await require_business_identity(CurrentUser(user_id=state["user_id"], tenant_id=state["tenant_id"]))
        from ..services.authorization_service import require_permission
        require_permission(actor, 'meeting', 'write')


async def review_meeting(state: MeetingState) -> dict:
    await _authorize(state)
    decision = interrupt({
        "type": "meeting_review", "thread_id": state.get("thread_id"),
        "meeting_id": state.get("business_id"), "version": state.get("meeting_version"),
        "external_writes": False,
    })
    await _authorize(state)
    if not isinstance(decision, dict) or decision.get("action") not in {"confirm", "reject", "regenerate"}:
        raise AppException(ErrorCode.INVALID_STATE, "会议决定无效", http_status=422)
    if decision["action"] == "regenerate":
        return {
            "meeting_command_key": decision["command_key"],
            "meeting_generation_action": "regenerate", "draft": None,
            "meeting_version": decision["version"], "meeting_status": "PROCESSING",
            "meeting_decision_key": decision["command_key"], "next_action": "generate", "error": None,
        }
    return {
        "meeting_decision_key": decision["command_key"],
        "meeting_status": "CONFIRMED" if decision["action"] == "confirm" else "REJECTED",
        "draft": decision["draft"], "meeting_version": decision["version"],
        "next_action": "completed" if decision["action"] == "confirm" else "rejected",
    }


def build_meeting_graph() -> StateGraph:
    graph = StateGraph(MeetingState)
    graph.add_node("parse_meeting", parse_meeting)
    graph.add_node("generate_mock_draft", generate_mock_draft)
    graph.add_edge(START, "parse_meeting")
    graph.add_edge("parse_meeting", "generate_mock_draft")
    graph.add_edge("generate_mock_draft", END)
    return graph
