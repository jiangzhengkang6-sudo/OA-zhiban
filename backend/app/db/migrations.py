"""Configuration and migration readiness checks, never startup schema mutation."""
from pathlib import Path
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory


def migration_config() -> Config:
    backend = Path(__file__).resolve().parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    return config


def validate_runtime_configuration(settings) -> None:
    if settings.oa_provider not in {'mock', 'real', 'builtin'}:
        raise RuntimeError('OA 服务提供方配置无效')
    if settings.auth_provider not in {'mock', 'builtin'}:
        raise RuntimeError("认证提供方尚未接入；禁止忽略认证配置回退为 Mock")
    if settings.environment.lower() in {"production", "prod"} and (settings.auth_provider == 'mock' or settings.oa_provider == 'mock'):
        raise RuntimeError("生产环境禁止 Mock 认证；请先接入正式认证适配器")
    if settings.auth_provider == 'builtin':
        from ..services.credential_service import validate_key
        validate_key(settings)
        from urllib.parse import urlparse
        if not settings.auth_allowed_origins or '*' in settings.auth_allowed_origins:
            raise RuntimeError('正式认证必须配置精确来源')
        for origin in settings.auth_allowed_origins:
            parsed = urlparse(origin)
            if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
                raise RuntimeError('认证来源格式无效')
            if settings.environment.lower() in {'prod', 'production'} and parsed.scheme != 'https':
                raise RuntimeError('生产认证来源必须使用 HTTPS')
            if not settings.auth_cookie_secure and (settings.environment.lower() in {'production','prod'} or parsed.hostname not in {'localhost','127.0.0.1'}):
                raise RuntimeError('非 Secure Cookie 只允许本地开发')
    if settings.oa_provider in {"real", "builtin"}:
        from ..providers.bundle import build_provider_bundle
        capabilities = build_provider_bundle(settings).capabilities
        if not (capabilities.identity and capabilities.leave_read and capabilities.approval_write):
            raise RuntimeError("真实 OA 适配器未完成能力探测；拒绝以 Mock 数据代替")


def assert_schema_current(connection):
    expected = set(ScriptDirectory.from_config(migration_config()).get_heads())
    actual = set(MigrationContext.configure(connection).get_current_heads())
    if actual != expected:
        raise RuntimeError("数据库结构未升级；请在 backend 执行 python -m alembic upgrade head（不会删除已有 MVP 数据）")
