"""
OA 智能体管理系统 - 依赖工厂。

按配置提供 OAAdapter 与 LLM/Embedding 客户端实例。MVP 默认 Mock；真实 OA/ARK 接入
后仅需在 .env 切换并实现对应类，业务代码无需改动。
"""

from functools import lru_cache

from ..core.config import get_settings
from .oa_adapter import OAAdapter


def get_adapter() -> OAAdapter:
    """获取 OA 适配器单例（按 OA_PROVIDER）。

    使用 lru_cache 返回同一实例，保证 Mock 的内存幂等状态跨请求保留。

    Returns:
        OAAdapter: mock 或真实实现。

    Raises:
        NotImplementedError: 配置为 real 但未实现时。
    """
    settings = get_settings()
    if settings.auth_provider == 'builtin' and settings.oa_provider == 'mock':
        from ..core.errors import AppException, ErrorCode
        raise AppException(ErrorCode.DEPENDENCY_FAILED, '该业务尚未接通正式 OA 服务', http_status=503)
    return _cached_adapter()


@lru_cache
def _cached_adapter():
    from ..providers.bundle import build_provider_bundle
    return build_provider_bundle(get_settings()).adapter


get_adapter.cache_clear = _cached_adapter.cache_clear
