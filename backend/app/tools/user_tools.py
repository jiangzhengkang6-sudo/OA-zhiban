"""
OA 智能体管理系统 - 用户上下文工具。

提供 get_user_context 工具：仅返回当前登录用户范围内的上下文，用于权限快照与身份
校验。任何场景通用，只读。
"""

from ..adapters.oa_adapter import OAAdapter


async def get_user_context(adapter: OAAdapter, user_id: str) -> dict:
    """读取用户上下文（身份/部门/角色/数据范围）。

    Args:
        adapter: OA 适配器。
        user_id: 用户 ID。

    Returns:
        dict: 用户上下文（dict 形式），用户不存在时返回空信息。

    Raises:
        ValueError: 用户不存在时。
    """
    ctx = adapter.get_user_context(user_id)
    if ctx is None:
        raise ValueError(f"用户 {user_id} 不存在")
    return ctx.model_dump()