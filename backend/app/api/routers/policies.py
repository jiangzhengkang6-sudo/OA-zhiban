"""
OA 智能体管理系统 - 智能策略管理接口路由。

提供场景开关/灰度/阈值/规则版本的查询与更新（仅管理员）：
    GET /api/admin/agent-policies
    PUT /api/admin/agent-policies
配置变更写入审计（AC-MVP-18）。
"""

from fastapi import APIRouter, Depends
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.enums import AuditAction
from ...db.session import get_db
from ...repositories import policy_repo
from ...schemas.common import ok
from ...schemas.policy import PolicyOut, PolicyUpdateRequest
from ...schemas.policy_version import PolicyVersionCreateRequest
from ...models.policy_version import PolicyVersion
from ...services import policy_version_service
from ...services import audit_service
from ...services import oa_scope_service
from ...core.config import get_settings
from ..deps import require_roles

router = APIRouter(prefix="/admin/agent-policies", tags=["admin-policies"])
version_router = APIRouter(prefix="/admin/agent-policy-versions", tags=["admin-policy-versions"])


@router.get("")
async def list_policies(
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("admin")),
):
    """列出策略配置。

    Args:
        session: 数据库会话。
        user: 当前用户（admin）。

    Returns:
        ApiResponse: 策略列表。
    """
    if get_settings().oa_provider == "builtin":
        policies = await oa_scope_service.list_formal_policies(session, tenant_id=user.tenant_id)
        result = []
        for policy in policies:
            formal = await oa_scope_service.formal_policy(session, actor=user, scene=policy.scene)
            version = formal.version if formal and formal.policy.id == policy.id else None
            result.append(_formal_policy_out(policy, version))
        return ok(result)
    policies = await policy_repo.list_policies(session)
    return ok([_to_out(p).model_dump() for p in policies])


@router.put("")
async def upsert_policy(
    payload: PolicyUpdateRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("admin")),
):
    """创建/更新策略并记录审计。

    Args:
        payload: 策略更新请求。
        session: 数据库会话。
        user: 当前用户（admin）。

    Returns:
        ApiResponse: 保存后的策略。
    """
    if get_settings().oa_provider == "builtin":
        try:
            policy, version = await oa_scope_service.upsert_formal_policy(
                session, actor=user, scene=payload.scene, scope_type=payload.scope_type,
                scope_value=payload.scope_value, enabled=payload.enabled,
                thresholds=payload.thresholds, rule_version=payload.rule_version)
        except ValueError as exc:
            from ...core.errors import AppException
            from ...core.enums import ErrorCode
            raise AppException(ErrorCode.BAD_REQUEST, str(exc)) from exc
        await oa_scope_service.record_audit(session, actor=user, resource="policy",
            action=AuditAction.POLICY_CHANGED.value, object_type="policy", object_id=str(policy.id),
            detail={"version": version.version, "enabled": payload.enabled})
        await session.commit()
        return ok(_formal_policy_out(policy, version))
    policy = await policy_repo.upsert_policy(
        session,
        scene=payload.scene,
        scope_type=payload.scope_type,
        scope_value=payload.scope_value,
        enabled=payload.enabled,
        thresholds=payload.thresholds,
        rule_version=payload.rule_version,
        updated_by=user.user_id,
    )
    # 记录配置变更审计（含前后版本）
    await audit_service.audit(
        session,
        AuditAction.POLICY_CHANGED.value,
        actor_id=user.user_id,
        target_type="policy",
        target_id=payload.scene,
        input_summary={
            "enabled": payload.enabled,
            "rule_version": payload.rule_version,
            "thresholds": payload.thresholds,
        },
    )
    await session.commit()
    return ok(_to_out(policy).model_dump())


def _to_out(p) -> PolicyOut:
    """ORM -> DTO。

    Args:
        p: 策略 ORM 对象。

    Returns:
        PolicyOut: DTO。
    """
    return PolicyOut(
        scene=p.scene,
        scope_type=p.scope_type,
        scope_value=p.scope_value,
        enabled=p.enabled,
        thresholds=p.thresholds or {},
        rule_version=p.rule_version,
        updated_by=p.updated_by,
    )


def _formal_policy_out(policy, version=None) -> dict:
    return {
        "scene": policy.scene, "scope_type": policy.scope_type, "scope_value": policy.scope_value,
        "enabled": bool(policy.enabled), "thresholds": (version.thresholds if version else {}),
        "rule_version": version.rule_version if version else "v1", "updated_by": version.created_by if version else None,
        "version": version.version if version else None, "status": version.status if version else "unpublished",
    }


def _version_out(p: PolicyVersion) -> dict:
    return {
        "id": str(p.id), "scene": p.scene, "scope_type": p.scope_type,
        "scope_value": p.scope_value, "version": p.version, "status": p.status,
        "enabled": p.enabled, "thresholds": p.thresholds or {},
        "rule_version": p.rule_version, "created_by": p.created_by,
        "published_at": p.published_at,
    }


@version_router.post("")
async def create_policy_version(
    payload: PolicyVersionCreateRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_roles("admin")),
):
    from ...core.enums import ErrorCode
    from ...core.errors import AppException
    if get_settings().oa_provider == "builtin":
        try:
            policy, version = await oa_scope_service.upsert_formal_policy(
                session, actor=user, scene=payload.scene, scope_type=payload.scope_type,
                scope_value=payload.scope_value, enabled=payload.enabled,
                thresholds=payload.thresholds, rule_version=payload.rule_version)
        except ValueError as exc:
            raise AppException(ErrorCode.BAD_REQUEST, str(exc)) from exc
        await session.commit()
        return ok({"id": str(version.id), "scene": policy.scene, "scope_type": policy.scope_type,
                   "scope_value": policy.scope_value, "version": version.version, "status": version.status,
                   "enabled": policy.enabled, "thresholds": version.thresholds or {},
                   "rule_version": version.rule_version, "created_by": version.created_by,
                   "published_at": version.published_at})
    try:
        version = await policy_version_service.create_version(
            session, created_by=user.user_id, **payload.model_dump()
        )
    except ValueError as exc:
        raise AppException(ErrorCode.BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return ok(_version_out(version))


@version_router.get("")
async def list_policy_versions(
    scene: str | None = None, session: AsyncSession = Depends(get_db), user=Depends(require_roles("admin"))
):
    if get_settings().oa_provider == "builtin":
        rows = await oa_scope_service.list_formal_versions(session, tenant_id=user.tenant_id, scene=scene)
        return ok([{"id": str(version.id), "scene": policy.scene, "scope_type": policy.scope_type,
                    "scope_value": policy.scope_value, "version": version.version, "status": version.status,
                    "enabled": policy.enabled, "thresholds": version.thresholds or {},
                    "rule_version": version.rule_version, "created_by": version.created_by,
                    "published_at": version.published_at} for version, policy in rows])
    rows = await policy_version_service.list_versions(session, scene=scene)
    return ok([_version_out(row) for row in rows])


@version_router.post("/{version_id}/publish")
async def publish_policy_version(
    version_id: UUID, session: AsyncSession = Depends(get_db), user=Depends(require_roles("admin"))
):
    from ...core.enums import ErrorCode
    from ...core.errors import AppException
    if get_settings().oa_provider == "builtin":
        version = await session.get(oa_scope_service.OAAgentPolicyVersion, str(version_id))
        if version is None or version.tenant_id != user.tenant_id:
            raise AppException(ErrorCode.BAD_REQUEST, "正式策略版本不存在")
        version.status = "published"
        await session.commit()
        policy = await session.get(oa_scope_service.OAAgentPolicy, version.policy_id)
        return ok({"id": str(version.id), "scene": policy.scene, "scope_type": policy.scope_type,
                   "scope_value": policy.scope_value, "version": version.version, "status": version.status,
                   "enabled": policy.enabled, "thresholds": version.thresholds or {},
                   "rule_version": version.rule_version, "created_by": version.created_by,
                   "published_at": version.published_at})
    try:
        version = await policy_version_service.publish_version(session, version_id)
    except ValueError as exc:
        raise AppException(ErrorCode.BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return ok(_version_out(version))


@version_router.post("/{version_id}/rollback")
async def rollback_policy_version(
    version_id: UUID, session: AsyncSession = Depends(get_db), user=Depends(require_roles("admin"))
):
    from ...core.enums import ErrorCode
    from ...core.errors import AppException
    try:
        version = await policy_version_service.rollback_version(session, version_id, created_by=user.user_id)
    except ValueError as exc:
        raise AppException(ErrorCode.BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return ok(_version_out(version))
