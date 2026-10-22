"""
OA 智能体管理系统 - 工单工具。

提供工单创建/合并（写工具，须用户确认+幂等键）与工单状态查询（只读）。
"""

from ..adapters.oa_adapter import OAAdapter, TicketCommand
from ..core.errors import AppException, ErrorCode


async def create_or_merge_ticket(
    adapter: OAAdapter, command: TicketCommand
) -> dict:
    """创建或合并工单（写操作，幂等）。

    Args:
        adapter: OA 适配器。
        command: 工单命令（含幂等键与抽取字段）。

    Returns:
        dict: 工单结果（含 ticket_id）。
    """
    from ..adapters.builtin_gateway import BuiltinGateway
    if isinstance(adapter, BuiltinGateway):
        return await adapter.create_or_merge_ticket(command)
    result = adapter.create_or_merge_ticket(command)
    return result.model_dump()


async def get_ticket_status(adapter: OAAdapter, ticket_id: str, user_id: str) -> dict:
    """查询工单状态（只读，仅返回用户有权查看的工单）。

    Args:
        adapter: OA 适配器。
        ticket_id: 工单号。
        user_id: 当前用户。

    Returns:
        dict: 工单信息。

    Raises:
        AppException: 工单不存在或无权查看时。
    """
    ticket = adapter.get_ticket_status(ticket_id)
    if ticket is None:
        raise AppException(ErrorCode.NOT_FOUND, "工单不存在", http_status=404)
    # 简单权限：仅创建者或客服可见（Mock）
    if ticket.get("user_id") != user_id and user_id not in ("u_cs_001", "u_admin_001"):
        raise AppException(ErrorCode.FORBIDDEN, "无权查看该工单", http_status=403)
    return ticket
