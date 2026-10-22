from app.core.context import set_trace_id
from app.schemas.common import ok


def test_success_envelope_includes_request_and_business_state():
    set_trace_id("trace-77")
    response = ok({"status": "WAITING_HUMAN"}).model_dump()
    assert response["request_id"] == response["trace_id"] == "trace-77"
    assert response["business_status"] == "WAITING_HUMAN"


def test_business_state_is_optional_for_lists():
    assert ok([]).model_dump()["business_status"] is None
