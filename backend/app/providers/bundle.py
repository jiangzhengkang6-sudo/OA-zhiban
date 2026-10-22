"""Never silently fall back to Mock for unimplemented production providers."""
from dataclasses import dataclass, field
from ..core.config import get_settings
from .base import ProviderCapabilities


@dataclass(frozen=True)
class MeetingCapabilities:
    text_input: bool = True
    external_writes: bool = False


@dataclass(frozen=True)
class ProviderBundle:
    name: str
    adapter: object
    capabilities: ProviderCapabilities
    meeting: MeetingCapabilities = field(default_factory=MeetingCapabilities)


def build_provider_bundle(settings=None) -> ProviderBundle:
    settings = settings or get_settings()
    if settings.oa_provider == "mock":
        if settings.environment.lower() in {"production", "prod"}:
            raise RuntimeError("生产禁止 Mock OA")
        from ..adapters.mock_adapter import MockAdapter
        return ProviderBundle("mock", MockAdapter(), ProviderCapabilities(True, True, True, True, True))
    if settings.oa_provider == "real":
        from ..adapters.real_adapter import RealOAAdapter
        adapter = RealOAAdapter(settings=settings)
        return ProviderBundle("real", adapter, adapter.probe_capabilities())
    if settings.oa_provider == "builtin":
        class BuiltinGatewayProvider:
            """Factory marker; a request must provide BridgeContext explicitly."""

            provider = "builtin"

            def for_context(self, context):
                from ..adapters.builtin_gateway import BuiltinGateway
                return BuiltinGateway(context)

            def __getattr__(self, name):
                raise RuntimeError(f"builtin 能力 {name} 必须通过 BridgeContext 异步网关调用")

        return ProviderBundle("builtin", BuiltinGatewayProvider(),
                              ProviderCapabilities(True, True, True, True, True))
    raise RuntimeError("不支持的 OA_PROVIDER，拒绝回退 Mock")
