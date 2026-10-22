from run import _build_server


def test_backend_uses_dedicated_port_by_default(monkeypatch):
    monkeypatch.delenv("OA_BACKEND_PORT", raising=False)
    assert _build_server().config.port == 8001


def test_backend_port_can_be_changed(monkeypatch):
    monkeypatch.setenv("OA_BACKEND_PORT", "8181")
    assert _build_server().config.port == 8181
