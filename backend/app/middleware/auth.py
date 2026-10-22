"""
OA 智能体管理系统 - OA 登录态复用中间件（Mock）。

MVP 阶段以 Mock JWT/HMAC 方式复用 OA 登录态：从 Authorization 头解析
``{user_id, tenant_id, roles, depts}``，挂载到 request.state 与 contextvars。
真实 OA 沙箱阶段仅需替换本文件的 token 校验与用户解析逻辑，其余不动。

约定（开发期）：Authorization 值为 ``Bearer mock:<user_id>`` 或直接裸 ``user_id``。
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ..adapters.mock_data import MOCK_USERS
from ..core.context import CurrentUser, set_current_user
from ..core.errors import AppException, ErrorCode
from ..core.config import get_settings


class AuthMiddleware(BaseHTTPMiddleware):
    """Mock 登录态解析中间件。"""

    async def dispatch(self, request: Request, call_next):
        """解析登录态并注入当前用户上下文。

        Args:
            request: HTTP 请求。
            call_next: 后续处理链。

        Returns:
            Response: 处理结果。

        Raises:
            不直接抛异常，无凭证时按匿名处理（由下游依赖拦截）。
        """
        set_current_user(None)
        request.state.user = None
        try:
            if get_settings().auth_provider == 'builtin':
                from ..services.identity_service import resolve_access
                from ..db.session import async_session_factory
                header = request.headers.get('Authorization', '')
                user = None
                if header.startswith('Bearer ') and not header[7:].startswith('mock:'):
                    try:
                        async with async_session_factory() as db:
                            user = await resolve_access(header[7:], session=db)
                    except AppException:
                        pass
            elif get_settings().auth_provider == 'mock':
                user = self._resolve_user(request)
            else:
                user = None
            set_current_user(user)
            request.state.user = user
            return await call_next(request)
        finally:
            set_current_user(None)

    def _resolve_user(self, request: Request):
        """从请求头解析当前用户。

        Args:
            request: HTTP 请求。

        Returns:
            Optional[CurrentUser]: 解析到的用户，无凭证时返回 None。
        """
        auth = request.headers.get("Authorization", "")
        if not auth:
            return None
        token = auth.removeprefix("Bearer ").strip()
        user_id = token.removeprefix("mock:")
        raw = MOCK_USERS.get(user_id)
        if not raw:
            return None
        return CurrentUser(
            user_id=raw["user_id"],
            tenant_id=raw["tenant_id"],
            roles=list(raw.get("roles", [])),
            depts=[raw.get("dept_id", "")],
            data_scope=raw.get("data_scope", {}),
        )
