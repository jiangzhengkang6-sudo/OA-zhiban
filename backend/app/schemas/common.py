"""
OA 智能体管理系统 - 通用 API 响应模型。

定义统一响应包装 ApiResponse 与分页结构，所有接口以如下结构返回：

    {"code": "0", "message": "ok", "trace_id": "...", "data": {...}}
"""

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应包装。

    Attributes:
        code: 业务错误码（见 ErrorCode）。
        message: 描述。
        trace_id: 本次请求 trace_id。
        data: 业务数据。
    """

    code: str = "0"
    message: str = "ok"
    trace_id: str = ""
    request_id: str = ""
    business_status: Optional[str] = None
    data: Optional[T] = None


class PageResult(BaseModel, Generic[T]):
    """分页结果。

    Attributes:
        items: 当前页数据。
        total: 总条数。
        page: 页码（1 起）。
        page_size: 每页条数。
    """

    items: list[T] = []
    total: int = 0
    page: int = 1
    page_size: int = 20


def ok(data=None, message: str = "ok") -> ApiResponse:
    """构造成功响应。

    Args:
        data: 业务数据。
        message: 描述。

    Returns:
        ApiResponse: 成功响应。
    """
    from ..core.context import get_trace_id

    trace_id = get_trace_id()
    payload = data.model_dump() if hasattr(data, "model_dump") else data
    status = payload.get("status") if isinstance(payload, dict) else None
    return ApiResponse(code="0", message=message, trace_id=trace_id,
                       request_id=trace_id, business_status=status, data=data)
