"""Scene degradation controls and runtime decisions."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.context import CurrentUser
from ..models.degradation_state import DegradationState


def _validate_scope(scope_type: str, scope_value: str | None) -> None:
    if scope_type == "global" and scope_value:
        raise ValueError("global degradation must not have a scope value")
    if scope_type != "global" and not scope_value:
        raise ValueError("scoped degradation requires a scope value")


def as_dict(state: DegradationState) -> dict:
    return {
        "id": str(state.id),
        "scene": state.scene,
        "scope_type": state.scope_type,
        "scope_value": state.scope_value,
        "enabled": state.enabled,
        "new_task_action": state.new_task_action,
        "inflight_action": state.inflight_action,
        "reason": state.reason,
        "created_by": state.created_by,
        "restored_by": state.restored_by,
        "restored_at": state.restored_at,
        "created_at": state.created_at,
    }


async def create(
    session: AsyncSession,
    *,
    actor_id: str,
    scene: str,
    scope_type: str = "global",
    scope_value: str | None = None,
    enabled: bool = True,
    new_task_action: str = "fallback",
    inflight_action: str = "continue",
    reason: str,
) -> DegradationState:
    _validate_scope(scope_type, scope_value)
    state = DegradationState(
        scene=scene,
        scope_type=scope_type,
        scope_value=scope_value,
        enabled=enabled,
        new_task_action=new_task_action,
        inflight_action=inflight_action,
        reason=reason,
        created_by=actor_id,
    )
    session.add(state)
    await session.flush()
    return state


async def list_states(session: AsyncSession) -> list[DegradationState]:
    result = await session.execute(
        select(DegradationState).order_by(DegradationState.created_at.desc())
    )
    return list(result.scalars().all())


async def restore(session: AsyncSession, state_id: UUID, *, actor_id: str) -> DegradationState:
    state = await session.get(DegradationState, state_id)
    if state is None:
        raise LookupError("degradation state not found")
    state.enabled = False
    state.restored_by = actor_id
    state.restored_at = datetime.now(timezone.utc)
    await session.flush()
    return state


async def resolve(
    session: AsyncSession,
    *,
    scene: str,
    user: CurrentUser,
) -> DegradationState | None:
    candidates = (
        ("user", user.user_id),
        *(("dept", dept) for dept in user.depts),
        ("tenant", user.tenant_id),
        ("global", None),
    )
    for scope_type, scope_value in candidates:
        result = await session.execute(
            select(DegradationState)
            .where(
                DegradationState.scene == scene,
                DegradationState.scope_type == scope_type,
                DegradationState.scope_value == scope_value,
                DegradationState.enabled.is_(True),
            )
            .order_by(DegradationState.created_at.desc())
            .limit(1)
        )
        state = result.scalar_one_or_none()
        if state is not None:
            return state
    return None
