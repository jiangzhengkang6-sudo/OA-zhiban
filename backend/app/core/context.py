"""
OA 智能体管理系统 - 请求上下文模块（contextvars）。

通过 contextvars 在异步请求生命周期内传递 trace_id 与当前用户，避免将上下文逐层
透传参数。中间件写入，业务/工具/审计层读取。每个请求/后台任务独立，天然隔离。
"""

import contextvars
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CurrentUser:
    """当前请求用户上下文快照。"""

    user_id: str
    tenant_id: str
    roles: list[str] = field(default_factory=list)
    depts: list[str] = field(default_factory=list)
    data_scope: dict = field(default_factory=dict)  # 数据权限范围
    session_id: str | None = None
    auth_version: int | None = None
    authorization_version: int | None = None


# trace_id：一次请求/一次图运行共享
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)
# current_user：当前登录用户
_current_user_var: contextvars.ContextVar[Optional[CurrentUser]] = (
    contextvars.ContextVar("current_user", default=None)
)
# policy_version：当前生效策略版本快照
_policy_version_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "policy_version", default=""
)


def set_trace_id(trace_id: str) -> None:
    """写入当前上下文的 trace_id。

    Args:
        trace_id: 全局唯一追踪 ID。
    """
    _trace_id_var.set(trace_id)


def get_trace_id() -> str:
    """读取当前 trace_id（未设置时返回空串）。

    Returns:
        str: trace_id。
    """
    return _trace_id_var.get()


def set_current_user(user: Optional[CurrentUser]) -> None:
    """写入当前用户上下文。

    Args:
        user: 当前用户快照。
    """
    _current_user_var.set(user)


def get_current_user() -> Optional[CurrentUser]:
    """读取当前用户上下文。

    Returns:
        Optional[CurrentUser]: 当前用户，未认证时为 None。
    """
    return _current_user_var.get()


def set_policy_version(version: str) -> None:
    """写入当前生效策略版本。

    Args:
        version: 策略版本号。
    """
    _policy_version_var.set(version)


def get_policy_version() -> str:
    """读取当前策略版本。

    Returns:
        str: 策略版本号。
    """
    return _policy_version_var.get()
