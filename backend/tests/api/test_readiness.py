"""Provider readiness is explicit and does not silently claim real OA availability."""

import pytest

from app.api.routers.readiness import readiness
from app.core.config import Settings


@pytest.mark.asyncio
async def test_default_mock_readiness_reports_capabilities(monkeypatch):
    from app.api.routers import readiness as readiness_module
    monkeypatch.setattr(readiness_module, "get_settings", lambda: Settings(_env_file=None, oa_provider="mock"))
    result = await readiness()
    assert result["provider"] == "mock"
    assert result["ready"] is True


@pytest.mark.asyncio
async def test_real_without_endpoint_is_not_ready(monkeypatch):
    from app.api.routers import readiness as readiness_module
    monkeypatch.setattr(readiness_module, "get_settings", lambda: Settings(_env_file=None, oa_provider="real", oa_base_url=""))
    result = await readiness()
    assert result["provider"] == "real"
    assert result["ready"] is False
