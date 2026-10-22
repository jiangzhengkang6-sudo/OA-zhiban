"""
OA 智能体管理系统 - trace_id 中间件。

为每个 HTTP 请求生成或透传 X-Trace-Id，写入 contextvars，并在响应头回传，实现
"一次请求 = 一个 trace_id" 贯穿日志、审计与 LangGraph 运行。
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from ..core.context import set_trace_id


class TraceMiddleware(BaseHTTPMiddleware):
    """trace_id 中间件：生成/透传并在响应头回传。"""

    async def dispatch(self, request: Request, call_next):
        """处理请求，注入并回传 trace_id。

        Args:
            request: HTTP 请求。
            call_next: 后续处理链。

        Returns:
            Response: 处理结果（响应头带 X-Trace-Id）。
        """
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex
        set_trace_id(trace_id)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response