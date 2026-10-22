import pytest
from app.core.config import Settings
from app.db.migrations import migration_config, validate_runtime_configuration


def test_production_cannot_use_mock_identity_or_oa():
    with pytest.raises(RuntimeError):
        validate_runtime_configuration(Settings(_env_file=None, environment="production"))


def test_unimplemented_identity_fails_closed():
    with pytest.raises(RuntimeError):
        validate_runtime_configuration(Settings(_env_file=None, auth_provider="unimplemented"))


def test_builtin_still_blocks_mock_oa_in_production():
    with pytest.raises(RuntimeError):
        validate_runtime_configuration(Settings(_env_file=None, environment='production', auth_provider='builtin',
            auth_jwt_secret='test-key-only-' * 4, oa_provider='mock'))


def test_builtin_development_requires_secure_origin_configuration():
    validate_runtime_configuration(Settings(_env_file=None, auth_provider='builtin',
        auth_jwt_secret='test-key-only-' * 4, auth_cookie_secure=False,
        auth_allowed_origins=['http://localhost:5182']))
    with pytest.raises(RuntimeError):
        validate_runtime_configuration(Settings(_env_file=None, auth_provider='builtin',
            auth_jwt_secret='test-key-only-' * 4, auth_cookie_secure=False,
            auth_allowed_origins=['http://external.test']))


def test_real_oa_stub_is_not_reported_ready():
    with pytest.raises(RuntimeError, match="真实 OA"):
        validate_runtime_configuration(Settings(_env_file=None, oa_provider="real"))


def test_migration_paths_do_not_depend_on_current_directory():
    config = migration_config()
    from pathlib import Path
    assert Path(config.get_main_option("script_location")).is_absolute()
    assert Path(config.get_main_option("script_location")).is_dir()
