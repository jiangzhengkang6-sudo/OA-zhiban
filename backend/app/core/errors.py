"""
OA 智能体管理系统 - 统一异常与错误处理模块。

定义 AppException 业务异常，携带错误码(ErrorCode)、HTTP 状态码、可选的细节与 trace_id，
供全局异常处理器转换为统一响应结构：

    {"code": "...", "message": "...", "detail": {...}, "trace_id": "..."}

业务代码抛 AppException 而非裸 Exception，保证错误语义与前端一致。
"""

from typing import Any, Optional

from .enums import ErrorCode


class AppException(Exception):
    """业务异常基类：携带统一错误码与 HTTP 状态码。

    Attributes:
        code: 业务错误码（ErrorCode）。
        message: 面向用户的错误描述。
        http_status: 映射到 HTTP 响应的状态码。
        detail: 可选的附加明细（如缺项列表、字段错误）。
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        http_status: int = 400,
        detail: Optional[Any] = None,
    ) -> None:
        """初始化业务异常。

        Args:
            code: 业务错误码。
            message: 错误描述。
            http_status: HTTP 状态码，默认 400。
            detail: 附加明细数据。
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = detail


# 常用异常便捷构造函数，避免业务层处处重复编码
def not_found(message: str, code: ErrorCode = ErrorCode.NOT_FOUND) -> AppException:
    """构造 404 资源不存在异常。

    Args:
        message: 错误描述。
        code: 业务错误码，默认 NOT_FOUND。

    Returns:
        AppException 实例。
    """
    return AppException(code, message, http_status=404)


def forbidden(message: str, code: ErrorCode = ErrorCode.FORBIDDEN) -> AppException:
    """构造 403 无权限异常（不泄露资源是否存在）。

    Args:
        message: 错误描述。
        code: 业务错误码，默认 FORBIDDEN。

    Returns:
        AppException 实例。
    """
    return AppException(code, message, http_status=403)


def conflict(message: str, code: ErrorCode) -> AppException:
    """构造 409 幂等/状态冲突异常。

    Args:
        message: 错误描述。
        code: 业务错误码。

    Returns:
        AppException 实例。
    """
    return AppException(code, message, http_status=409)


def dependency_failed(message: str, detail: Optional[Any] = None) -> AppException:
    """构造 502 OA 依赖失败异常（流程置 PAUSED）。

    Args:
        message: 错误描述。
        detail: 附加明细。

    Returns:
        AppException 实例。
    """
    return AppException(ErrorCode.DEPENDENCY_FAILED, message, http_status=502, detail=detail)