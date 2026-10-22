"""
OA 智能体管理系统 - 审批落库写工具。

提供 create_or_update_oa_approval 写工具：仅在 HITL 通过后由节点调用，携带幂等键
（= business_id），确保重复执行不产生重复业务写。
"""

from ..adapters.oa_adapter import OAAdapter, ApprovalCommand


async def create_or_update_oa_approval(
    adapter: OAAdapter, command: ApprovalCommand
) -> dict:
    """创建/更新 OA 审批任务（写操作，幂等）。

    Args:
        adapter: OA 适配器。
        command: 审批落库命令（含 action/actor/幂等键）。

    Returns:
        dict: OA 操作结果。
    """
    if getattr(adapter, 'provider', None) == 'builtin':
        return await adapter.create_or_update_approval(command)
    result = adapter.create_or_update_approval(command)
    return result.model_dump()
