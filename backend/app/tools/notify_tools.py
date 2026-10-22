"""
OA 智能体管理系统 - 通知写工具。

提供 notify_user 写工具：复用 OA 通知渠道发送通知，并记录发送结果。
"""

from ..adapters.oa_adapter import OAAdapter, NotificationCommand


async def notify_user(
    adapter: OAAdapter,
    *,
    user_id: str,
    title: str,
    body: str,
    business_id: str = "",
    idempotency_key: str = "",
) -> dict:
    """发送通知（复用 OA 通知渠道）。

    Args:
        adapter: OA 适配器。
        user_id: 接收人。
        title: 通知标题。
        body: 通知正文。
        business_id: 业务单据号。
        idempotency_key: 幂等键。

    Returns:
        dict: 发送结果。
    """
    command = NotificationCommand(
        user_id=user_id,
        title=title,
        body=body,
        business_id=business_id,
        idempotency_key=idempotency_key,
    )
    result = adapter.notify(command)
    return result.model_dump()