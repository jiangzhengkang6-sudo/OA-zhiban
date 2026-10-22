"""Validation and lifecycle for immutable policy snapshots."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.policy_version import PolicyVersion


def choose_scope(user_id: str | None, dept_id: str | None, tenant_id: str | None) -> list[str]:
    return [value for value in (user_id, dept_id, tenant_id, "global") if value]


def validate_thresholds(thresholds: dict) -> None:
    confidence_keys = {
        "faq_answer",
        "intent_confidence",
        "faq_answer_threshold",
        "intent_confidence_threshold",
    }
    for key, value in thresholds.items():
        if key.endswith("_seconds") and (not isinstance(value, (int, float)) or value < 0):
            raise ValueError(f"{key} must be non-negative")
        if key in confidence_keys and (not isinstance(value, (int, float)) or not 0 <= value <= 1):
            raise ValueError(f"{key} must be between 0 and 1")
    nudge = thresholds.get("nudge_after_seconds")
    escalate = thresholds.get("escalate_after_seconds")
    if nudge is not None and escalate is not None and escalate < nudge:
        raise ValueError("escalate_after_seconds must not be earlier than nudge_after_seconds")


async def create_version(session: AsyncSession, *, created_by: str, **payload) -> PolicyVersion:
    validate_thresholds(payload.get("thresholds") or {})
    rows = (await session.execute(select(PolicyVersion.version).where(
        PolicyVersion.scene == payload["scene"],
        PolicyVersion.scope_type == payload["scope_type"],
        PolicyVersion.scope_value == payload.get("scope_value"),
    ))).scalars().all()
    version = PolicyVersion(
        **payload, version=max(rows, default=0) + 1, status="draft", created_by=created_by,
    )
    session.add(version)
    await session.flush()
    return version


async def publish_version(session: AsyncSession, version_id: UUID) -> PolicyVersion:
    version = await session.get(PolicyVersion, version_id)
    if version is None:
        raise ValueError("policy version not found")
    await session.execute(update(PolicyVersion).where(
        PolicyVersion.scene == version.scene,
        PolicyVersion.scope_type == version.scope_type,
        PolicyVersion.scope_value == version.scope_value,
        PolicyVersion.status == "published",
        PolicyVersion.id != version.id,
    ).values(status="offline"))
    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    await session.flush()
    return version


async def rollback_version(session: AsyncSession, version_id: UUID, *, created_by: str) -> PolicyVersion:
    source = await session.get(PolicyVersion, version_id)
    if source is None:
        raise ValueError("policy version not found")
    clone = await create_version(
        session, created_by=created_by, scene=source.scene, scope_type=source.scope_type,
        scope_value=source.scope_value, enabled=source.enabled, thresholds=dict(source.thresholds or {}),
        rule_version=source.rule_version,
    )
    return await publish_version(session, clone.id)


async def list_versions(session: AsyncSession, *, scene: str | None = None) -> list[PolicyVersion]:
    stmt = select(PolicyVersion).order_by(PolicyVersion.scene, PolicyVersion.scope_type, PolicyVersion.version.desc())
    if scene:
        stmt = stmt.where(PolicyVersion.scene == scene)
    return list((await session.execute(stmt)).scalars().all())


async def resolve_snapshot(
    session: AsyncSession, *, scene: str, user_id: str | None, dept_id: str | None, tenant_id: str | None
) -> PolicyVersion | None:
    candidates = {"user": user_id, "dept": dept_id, "tenant": tenant_id, "global": None}
    for scope_type in ("user", "dept", "tenant", "global"):
        value = candidates[scope_type]
        row = (await session.execute(
            select(PolicyVersion)
            .where(
                PolicyVersion.scene == scene, PolicyVersion.scope_type == scope_type,
                PolicyVersion.scope_value == value, PolicyVersion.status == "published",
            )
            .order_by(PolicyVersion.version.desc())
            .limit(1)
        )).scalar_one_or_none()
        if row is not None:
            return row
    return None
