"""Operations metrics and trace drilldown endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.context import get_current_user
from ...db.session import get_db
from ...schemas.common import ok
from ...schemas.operations import DegradationCreateRequest
from ...services import degradation_service
from ...services import runtime_trace_service
from ..deps import require_roles

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/metrics")
async def get_metrics(trace_id: str | None = Query(default=None), session: AsyncSession = Depends(get_db), user=Depends(require_roles("admin"))):
    return ok(await runtime_trace_service.metrics(session, tenant_id=user.tenant_id, trace_id=trace_id))


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, session: AsyncSession = Depends(get_db), user=Depends(require_roles("admin"))):
    return ok(await runtime_trace_service.trace_detail(session, tenant_id=user.tenant_id, trace_id=trace_id))


@router.get("/degradations")
async def list_degradations(
    session: AsyncSession = Depends(get_db), user=Depends(require_roles("admin"))
):
    return ok([degradation_service.as_dict(row) for row in await degradation_service.list_states(session)])


@router.post("/degradations")
async def create_degradation(
    payload: DegradationCreateRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("admin")),
):
    try:
        state = await degradation_service.create(
            session,
            actor_id=user.user_id,
            **payload.model_dump(),
        )
    except ValueError as exc:
        from ...core.errors import AppException, ErrorCode
        raise AppException(ErrorCode.BAD_REQUEST, str(exc), http_status=400) from exc
    await session.commit()
    return ok(degradation_service.as_dict(state))


@router.post("/degradations/{state_id}/restore")
async def restore_degradation(
    state_id: UUID,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("admin")),
):
    try:
        state = await degradation_service.restore(session, state_id, actor_id=user.user_id)
    except LookupError as exc:
        from ...core.errors import not_found
        raise not_found("降级状态不存在") from exc
    await session.commit()
    return ok(degradation_service.as_dict(state))
