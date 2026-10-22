"""Read-only provider readiness and capability reporting."""

from fastapi import APIRouter

from ...core.config import get_settings
from ...providers.bundle import build_provider_bundle

router = APIRouter(prefix="/readiness", tags=["readiness"])


@router.get("")
async def readiness():
    settings = get_settings()
    bundle = build_provider_bundle(settings)
    capabilities = bundle.capabilities
    required = ("identity", "leave_read", "approval_write")
    return {
        "provider": bundle.name,
        "ready": all(getattr(capabilities, item) for item in required),
        "capabilities": {name: bool(getattr(capabilities, name)) for name in capabilities.__dataclass_fields__},
    }
