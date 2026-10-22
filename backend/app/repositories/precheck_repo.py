"""
OA 智能体管理系统 - 预检结果数据访问层。

提供预检结果的逐项写入，供请假预检节点持久化四项检查结果。
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..models.precheck_result import PrecheckResult


async def add_result(
    session: AsyncSession,
    *,
    thread_id: UUID,
    business_id: Optional[str],
    rule_version: Optional[str],
    item: str,
    result: str,
    reason: Optional[str] = None,
    evidence: Optional[dict] = None,
    suggestion: Optional[str] = None,
) -> PrecheckResult:
    """写入一条预检结果。

    Args:
        session: 数据库会话。
        thread_id: 会话 ID。
        business_id: 业务单据号。
        rule_version: 规则版本。
        item: 检查项。
        result: 判定结果。
        reason: 原因。
        evidence: 证据。
        suggestion: 建议。

    Returns:
        PrecheckResult: 写入的结果记录。
    """
    record = PrecheckResult(
        thread_id=thread_id,
        business_id=business_id,
        rule_version=rule_version,
        item=item,
        result=result,
        reason=reason,
        evidence=evidence,
        suggestion=suggestion,
    )
    session.add(record)
    await session.flush()
    return record