from app.adapters.factory import get_adapter
from app.adapters.mock_adapter import MockAdapter
from app.adapters.oa_adapter import NotificationCommand


def test_mock_notification_survives_restart_without_resending():
    adapter = get_adapter()
    cmd = NotificationCommand(user_id="u_mgr_001", title="催办", body="申请待审批",
                              idempotency_key="nudge-restart-test")
    before = len(adapter._state["notifications"])
    adapter.notify(cmd)
    adapter.notify(cmd)
    restarted = MockAdapter()
    restarted.notify(cmd)
    assert len(restarted._state["notifications"]) == before + 1
