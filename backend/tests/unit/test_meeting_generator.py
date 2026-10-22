from app.schemas.meeting import MeetingDraftDTO
from app.services.meeting_parser import MeetingParser


def test_rule_generator_extracts_only_cited_candidates_and_keeps_missing_fields_uncertain():
    from app.services.meeting_generator import generate_meeting_draft

    segments = [item.model_dump() for item in MeetingParser().parse(
        "议题：验收安排。决定：采用灰度发布。待办：完成验收。"
    )]
    draft = MeetingDraftDTO.model_validate(generate_meeting_draft(segments))
    assert draft.topics == ["验收安排"]
    assert draft.decisions[0].text == "采用灰度发布"
    assert draft.decisions[0].confidence == "explicit"
    action = draft.action_items[0]
    assert action.title == "完成验收"
    assert action.assignee_candidate is None and action.due_at_candidate is None
    assert action.needs_confirmation
    assert draft.decisions[0].source_refs == [segments[1]["segment_id"]]
    assert action.source_refs == [segments[2]["segment_id"]]


def test_rule_generator_does_not_turn_speculation_into_a_decision():
    from app.services.meeting_generator import generate_meeting_draft

    segments = [item.model_dump() for item in MeetingParser().parse("也许明天上线？负责人还没定。")]
    draft = generate_meeting_draft(segments)
    assert draft["decisions"] == []
    assert draft["action_items"] == []


def test_rule_generator_preserves_explicit_owner_and_date_as_candidates():
    from app.services.meeting_generator import generate_meeting_draft

    segments = [item.model_dump() for item in MeetingParser().parse(
        "待办：完成验收，负责人：李雷，截止时间：2026-10-30。"
    )]
    action = generate_meeting_draft(segments)["action_items"][0]
    assert action["assignee_candidate"] == "李雷"
    assert action["due_at_candidate"] == "2026-10-30"
    assert action["needs_confirmation"] is True
