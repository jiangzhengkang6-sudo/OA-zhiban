"""
OA 智能体管理系统 - 图工具函数。

提供图节点复用的辅助函数（如构造 HITL 中断负载），避免各子图重复实现。
"""

from .state import AgentState


def interrupt_payload(state: AgentState) -> dict:
    """构造统一的 HITL 中断负载。

    负载需是可序列化到 checkpoint 的纯 dict，包含定位与摘要信息，供人工侧展示。

    Args:
        state: 图状态。

    Returns:
        dict: 中断负载（thread_id/business_id/intent/next_action）。
    """
    return {
        "thread_id": state.get("thread_id"),
        "business_id": state.get("business_id"),
        "user_id": state.get("user_id"),
        "intent": state.get("intent"),
        "next_action": state.get("next_action"),
    }