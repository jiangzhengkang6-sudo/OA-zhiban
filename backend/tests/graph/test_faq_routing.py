from app.graph.superagent import _after_classify, _after_faq
from app.graph.faq_graph import _entry as faq_entry
from app.graph.ticket_graph import _entry as ticket_entry


def test_faq_uncertain_stays_in_human_handoff_without_ticket_draft():
    assert _after_faq({"scene": "faq", "next_action": "human"}) == "audit_tail"


def test_selected_faq_scene_overrides_ticket_classification():
    assert _after_classify({"scene": "faq", "intent": "ticket"}) == "faq"
    assert _after_classify({"scene": "ticket", "intent": "faq"}) == "ticket"


def test_explicit_human_intent_skips_retrieval_and_ticket_extraction():
    assert faq_entry({"intent": "human"}) == "human"
    assert ticket_entry({"intent": "human"}) == "human"
