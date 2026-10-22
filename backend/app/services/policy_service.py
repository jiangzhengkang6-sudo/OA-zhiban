"""
OA 智能体管理系统 - 策略服务。

负责读取场景开关、灰度范围与阈值，判断用户是否走智能路径。智能层关闭或未命中
灰度白名单时返回 False，由调用方走原 OA 路径（降级）。
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..repositories import policy_repo
from . import policy_version_service
from ..core.context import set_policy_version


async def is_scene_enabled(
    session: AsyncSession, scene: str, user_id: str, dept_id: str, tenant_id: str | None = None
) -> bool:
    """判断某场景智能路径是否对当前用户启用。

    规则（MVP）：
    1. 存在全局(global)策略且 enabled=False -> 关闭。
    2. 存在部门(dept)或用户(user)级别的显式白名单策略 -> 仅命中者启用。
    3. 无任何可判定策略 -> 默认启用（开发模式全局智能路径开启）。

    Args:
        session: 数据库会话。
        scene: 场景。
        user_id: 用户 ID。
        dept_id: 部门 ID。

    Returns:
        bool: 是否启用智能路径。
    """
    if get_settings().oa_provider == "builtin":
        from .oa_scope_service import formal_policy
        from ..core.context import CurrentUser
        actor = CurrentUser(user_id=user_id, tenant_id=tenant_id or "", depts=[dept_id] if dept_id else [])
        formal = await formal_policy(session, actor=actor, scene=scene)
        return True if formal is None else bool(formal.status == "published" and formal.enabled)

    version = await policy_version_service.resolve_snapshot(
        session, scene=scene, user_id=user_id, dept_id=dept_id, tenant_id=tenant_id
    )
    if version is not None:
        set_policy_version(f"{version.scene}:{version.version}")
        return version.enabled

    global_policy = await policy_repo.get_policy(session, scene, "global", None)
    if global_policy is not None and not global_policy.enabled:
        return False

    # 部门/用户级覆盖：有显式白名单则仅命中者启用
    dept_policy = await policy_repo.get_policy(session, scene, "dept", dept_id)
    user_policy = await policy_repo.get_policy(session, scene, "user", user_id)
    has_scope_policy = dept_policy is not None or user_policy is not None
    if has_scope_policy:
        if user_policy is not None:
            return user_policy.enabled
        return bool(dept_policy and dept_policy.enabled)

    return True


async def get_thresholds(
    session: AsyncSession, scene: str, *, user_id: str | None = None,
    dept_id: str | None = None, tenant_id: str | None = None
) -> dict:
    """读取场景阈值（合并默认配置），供图节点使用。

    Args:
        session: 数据库会话。
        scene: 场景。

    Returns:
        dict: 阈值字典。
    """
    settings = get_settings()
    defaults = {
        "intent_confidence": settings.intent_confidence_threshold,
        "faq_answer": settings.faq_answer_threshold,
        "nudge_after_seconds": settings.nudge_after_seconds,
        "escalate_after_seconds": settings.escalate_after_seconds,
    }
    if get_settings().oa_provider == "builtin":
        from .oa_scope_service import formal_policy
        from ..core.context import CurrentUser
        actor = CurrentUser(user_id=user_id or "", tenant_id=tenant_id or "", depts=[dept_id] if dept_id else [])
        formal = await formal_policy(session, actor=actor, scene=scene) if user_id and tenant_id else None
        if formal is not None and formal.status == "published":
            defaults.update(_normalize_thresholds(formal.thresholds or {}))
            defaults["policy_version"] = formal.version_number
        return defaults

    version = await policy_version_service.resolve_snapshot(
        session, scene=scene, user_id=user_id, dept_id=dept_id, tenant_id=tenant_id
    )
    if version is not None:
        set_policy_version(f"{version.scene}:{version.version}")
        defaults.update(_normalize_thresholds(version.thresholds or {}))
        defaults["policy_version"] = version.version
        return defaults
    policy = await policy_repo.get_policy(session, scene, "global", None)
    if policy and policy.thresholds:
        defaults.update(_normalize_thresholds(policy.thresholds))
    return defaults


def _normalize_thresholds(values: dict) -> dict:
    """Accept both legacy short names and explicit versioned names."""
    result = dict(values)
    aliases = {
        "faq_answer_threshold": "faq_answer",
        "intent_confidence_threshold": "intent_confidence",
    }
    for source, target in aliases.items():
        if source in result and target not in result:
            result[target] = result[source]
    return result
