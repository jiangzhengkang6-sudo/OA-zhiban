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


def production_settings(**overrides):
    values = dict(environment='production', auth_provider='builtin', oa_provider='builtin',
                  auth_jwt_secret='synthetic-signing-key-' * 3,
                  auth_allowed_origins=['https://oa.example.test'], auth_cookie_secure=True,
                  database_url='postgresql+asyncpg://oa:Synthetic-Strong-487!@m4-db/oa_m4_config_test',
                  database_sync_url='postgresql+psycopg://oa:Synthetic-Strong-487!@m4-db/oa_m4_config_test',
                  checkpointer_url='postgresql://oa:Synthetic-Strong-487!@m4-db/oa_m4_config_test')
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize('field', ['database_url', 'database_sync_url', 'checkpointer_url'])
@pytest.mark.parametrize('password', ['', 'oa', 'postgres', 'password', 'changeme', 'change-me-before-production', 'aaaaaaaaaaaaaaaaaaaa'])
def test_production_rejects_unsafe_database_credentials(field, password):
    with pytest.raises(RuntimeError, match='数据库'):
        validate_runtime_configuration(production_settings(**{
            field: f'postgresql://oa:{password}@m4-db/oa_m4_config_test'}))


@pytest.mark.parametrize('value', ['invalid-url', 'sqlite:///local.db', 'postgresql://oa@host/db',
                                  'postgresql://oa:Synthetic-Strong-487!@/db'])
def test_production_rejects_incomplete_database_urls_without_leaking(value):
    with pytest.raises(RuntimeError, match='数据库') as error:
        validate_runtime_configuration(production_settings(checkpointer_url=value))
    assert value not in str(error.value)
    assert 'Synthetic-Strong-487!' not in str(error.value)
    assert error.value.__cause__ is None


def test_production_accepts_explicit_database_credentials():
    validate_runtime_configuration(production_settings())


@pytest.mark.parametrize('environment', ['test', 'development'])
def test_nonproduction_keeps_mock_preview_compatible(environment):
    validate_runtime_configuration(Settings(_env_file=None, environment=environment,
                                           auth_provider='mock', oa_provider='mock'))
