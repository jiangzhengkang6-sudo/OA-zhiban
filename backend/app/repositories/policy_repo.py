"""
OA 智能体管理系统 - 策略数据访问层。

提供智能策略（开关/灰度/阈值/规则版本）的查询与更新，支持按场景与作用范围匹配。
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.agent_policy import AgentPolicy


async def get_policy(
    session: AsyncSession,
    scene: str,
    scope_type: str = "global",
    scope_value: Optional[str] = None,
) -> Optional[AgentPolicy]:
    """查询指定场景与作用的生效策略。

    Args:
        session: 数据库会话。
        scene: 场景。
        scope_type: 作用范围类型。
        scope_value: 作用范围值。

    Returns:
        Optional[AgentPolicy]: 命中的策略，无则 None。
    """
    stmt = select(AgentPolicy).where(
        AgentPolicy.scene == scene,
        AgentPolicy.scope_type == scope_type,
        AgentPolicy.scope_value == scope_value,
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def list_policies(session: AsyncSession, scene: Optional[str] = None) -> list[AgentPolicy]:
    """列出策略（可按场景过滤）。

    Args:
        session: 数据库会话。
        scene: 场景过滤（可选）。

    Returns:
        list[AgentPolicy]: 策略列表。
    """
    stmt = select(AgentPolicy)
    if scene:
        stmt = stmt.where(AgentPolicy.scene == scene)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def upsert_policy(
    session: AsyncSession,
    *,
    scene: str,
    scope_type: str,
    scope_value: Optional[str],
    enabled: bool,
    thresholds: Optional[dict],
    rule_version: str,
    updated_by: str,
) -> AgentPolicy:
    """创建或更新策略（记录操作者与版本）。

    Args:
        session: 数据库会话。
        scene: 场景。
        scope_type: 作用范围类型。
        scope_value: 作用范围值。
        enabled: 是否启用。
        thresholds: 阈值配置。
        rule_version: 规则版本。
        updated_by: 更新人。

    Returns:
        AgentPolicy: 保存后的策略。
    """
    policy = await get_policy(session, scene, scope_type, scope_value)
    if policy is None:
        policy = AgentPolicy(
            scene=scene, scope_type=scope_type, scope_value=scope_value,
            enabled=enabled, thresholds=thresholds, rule_version=rule_version,
            updated_by=updated_by,
        )
        session.add(policy)
    else:
        policy.enabled = enabled
        policy.thresholds = thresholds
        policy.rule_version = rule_version
        policy.updated_by = updated_by
    await session.flush()
    return policy