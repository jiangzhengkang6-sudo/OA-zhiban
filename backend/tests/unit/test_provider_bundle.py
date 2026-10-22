import pytest
from app.providers.bundle import build_provider_bundle
from app.core.config import Settings
from app.adapters.mock_adapter import MockAdapter


def test_mock_bundle_has_explicit_capabilities():
    bundle = build_provider_bundle(Settings(_env_file=None, oa_provider="mock"))
    assert bundle.name == "mock"
    assert isinstance(bundle.adapter, MockAdapter)
    assert bundle.capabilities.leave_read
    assert bundle.capabilities.approval_write


def test_builtin_has_explicit_gateway_factory_and_is_not_mocked():
    bundle = build_provider_bundle(Settings(_env_file=None, oa_provider="builtin"))
    assert bundle.name == "builtin"
    assert bundle.adapter.provider == "builtin"
    assert not isinstance(bundle.adapter, MockAdapter)


def test_unknown_provider_is_not_silently_mocked():
    with pytest.raises(RuntimeError):
        build_provider_bundle(Settings(_env_file=None, oa_provider="unknown"))


def test_real_is_unavailable_not_reported_as_ready():
    bundle = build_provider_bundle(Settings(_env_file=None, oa_provider="real"))
    assert not bundle.capabilities.approval_write


def test_meeting_capability_is_platform_local_for_every_provider():
    for provider in ("mock", "real"):
        bundle = build_provider_bundle(Settings(_env_file=None, oa_provider=provider))
        assert bundle.meeting.text_input is True
        assert bundle.meeting.external_writes is False
