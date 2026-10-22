import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url


def load_preview():
    path = Path(__file__).resolve().parents[2] / 'scripts' / 'm3_preview.py'
    spec = importlib.util.spec_from_file_location('m3_preview_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preview_configuration_is_isolated(monkeypatch):
    module = load_preview()
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    monkeypatch.setenv('M3_DATABASE_SERVER_URL', 'postgresql://oa:oa@localhost:5433/postgres')
    module.configure()
    assert module.PREVIEW_DB == 'oa_business_m3_preview_test'
    assert os.environ['ENVIRONMENT'] == 'development'
    assert os.environ['AUTH_TENANT_ID'] == 'm3-preview'
    assert os.environ['LLM_PROVIDER'] == 'mock'
    assert os.environ['EMBEDDING_PROVIDER'] == 'mock'
    assert os.environ['SMTP_ENABLED'] == 'false'
    assert os.environ['OA_BACKEND_PORT'] == '8015'


def test_preview_database_name_is_allowlisted():
    module = load_preview()
    assert module.PREVIEW_DB in module.DATABASES
    assert module.PREVIEW_DB != 'oa_agent_test'


def test_preview_uses_same_server_for_all_three_urls(monkeypatch, tmp_path):
    module = load_preview()
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    monkeypatch.setattr(module, 'OUTPUT', tmp_path)
    monkeypatch.setenv('M3_DATABASE_SERVER_URL', 'postgresql://preview:p%40ss@db.example.test:6432/postgres')
    module.configure()
    targets = [make_url(os.environ[name]) for name in ('DATABASE_URL', 'DATABASE_SYNC_URL', 'CHECKPOINTER_URL')]
    assert {url.host for url in targets} == {'db.example.test'}
    assert {url.port for url in targets} == {6432}
    assert {url.username for url in targets} == {'preview'}
    assert {url.password for url in targets} == {'p@ss'}
    assert {url.database for url in targets} == {module.PREVIEW_DB}


def test_preview_rejects_non_postgres_before_writing_environment(monkeypatch, tmp_path):
    module = load_preview()
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    monkeypatch.setattr(module, 'OUTPUT', tmp_path)
    monkeypatch.setenv('M3_DATABASE_SERVER_URL', 'sqlite:///production.db')
    before = os.environ.copy()
    with pytest.raises(RuntimeError):
        module.configure()
    assert os.environ == before
    assert not list(tmp_path.iterdir())
