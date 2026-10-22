"""Configuration and migration readiness checks, never startup schema mutation."""
from pathlib import Path
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url


def _validate_production_database_urls(settings) -> None:
    for field in ('database_url', 'database_sync_url', 'checkpointer_url'):
        try:
            url = make_url(getattr(settings, field))
            password = url.password or ''
            normalized = password.casefold()
            unsafe = (
                url.get_backend_name() != 'postgresql'
                or not url.host or not url.database or not url.username
                or len(password.encode('utf-8')) < 16 or len(set(password)) < 6
                or normalized in {'postgres', 'password', 'changeme', 'oa'}
                or any(marker in normalized for marker in ('change-me', 'changeme', 'replace-me', 'your-password'))
                or password == url.username
            )
            if url.port is not None and not 1 <= url.port <= 65535:
                unsafe = True
        except Exception:
            unsafe = True
        if unsafe:
            raise RuntimeError(f'生产数据库配置 {field} 无效：须使用完整 PostgreSQL 连接和至少 16 字节的非默认独立口令') from None


def migration_config() -> Config:
    backend = Path(__file__).resolve().parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    return config


def validate_runtime_configuration(settings) -> None:
    production = settings.environment.lower() in {'production', 'prod'}
    if settings.oa_provider not in {'mock', 'real', 'builtin'}:
        raise RuntimeError('OA 服务提供方配置无效')
    if settings.auth_provider not in {'mock', 'builtin'}:
        raise RuntimeError("认证提供方尚未接入；禁止忽略认证配置回退为 Mock")
    if production and (settings.auth_provider == 'mock' or settings.oa_provider == 'mock'):
        raise RuntimeError("生产环境禁止 Mock 认证；请先接入正式认证适配器")
    if production:
        _validate_production_database_urls(settings)
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
            if production and parsed.scheme != 'https':
                raise RuntimeError('生产认证来源必须使用 HTTPS')
            if not settings.auth_cookie_secure and (production or parsed.hostname not in {'localhost','127.0.0.1'}):
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
