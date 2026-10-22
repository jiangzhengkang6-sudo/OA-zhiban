"""Preflight must not send mail, write data or turn simulations into live passes."""
import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.ops import live_services as live


@pytest.fixture
def configured(monkeypatch):
    settings = Settings(_env_file=None, ai_enabled=True, llm_provider="ark",
                        llm_fallback_provider="deepseek", embedding_provider="ark",
                        embedding_dim=1024, smtp_enabled=True, wecom_enabled=True,
                        auth_provider="builtin", oa_provider="builtin", auth_tenant_id="local",
                        wecom_tenant_id="local", wecom_department_id="department",
                        wecom_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=private-key",
                        smtp_host="smtp.example.test", smtp_username="user", smtp_password="secret",
                        smtp_from="user@example.test", smtp_starttls=True)
    monkeypatch.setattr(live, "get_settings", lambda: settings)
    monkeypatch.setattr(live, "validate_runtime_configuration", lambda _: None)

    async def database(_):
        return {"schema_current": True, "vector_type": "vector(1024)", "chunks": 3,
                "missing": 0, "mismatched": 0, "wecom_scope_exists": True}

    async def text(provider):
        return {"provider": provider}

    async def embedding(_):
        return {"dimension": 1024}

    monkeypatch.setattr(live, "database_snapshot", database)
    monkeypatch.setattr(live, "text_probe", text)
    monkeypatch.setattr(live, "embedding_probe", embedding)
    monkeypatch.setattr(live, "smtp_authenticate", lambda _: None)
    return settings


def by_name(report):
    return {item["check"]: item for item in report["checks"]}


@pytest.mark.asyncio
async def test_live_passes_do_not_claim_delivery_or_production_acceptance(configured):
    report = await live.verify_services()
    checks = by_name(report)
    assert report["failures"] == 0
    assert report["production_acceptance"] is False
    assert checks["text_primary"]["provider"] == "ark"
    assert checks["text_fallback"]["provider"] == "deepseek"
    assert checks["smtp_authentication"]["message_sent"] is False
    for name in ("smtp_delivery", "wecom_delivery", "knowledge_vector_provenance"):
        assert checks[name]["status"] == "UNVERIFIED"
    assert "private-key" not in json.dumps(report)


@pytest.mark.asyncio
async def test_mock_models_never_make_live_calls_or_pass(configured, monkeypatch):
    configured.llm_provider = configured.embedding_provider = "mock"
    configured.llm_fallback_provider = "none"
    def forbidden(*_):
        pytest.fail("mock mode must not contact a model")
    monkeypatch.setattr(live, "text_probe", forbidden)
    monkeypatch.setattr(live, "embedding_probe", forbidden)
    checks = by_name(await live.verify_services())
    assert checks["text_primary"]["status"] == checks["embedding"]["status"] == "MOCK"


@pytest.mark.asyncio
async def test_ai_disabled_does_not_probe_models_even_with_standby_option(configured, monkeypatch):
    configured.ai_enabled = False
    monkeypatch.setattr(live, "text_probe", lambda *_: pytest.fail("AI disabled"))
    monkeypatch.setattr(live, "embedding_probe", lambda *_: pytest.fail("AI disabled"))
    checks = by_name(await live.verify_services(include_standby=True))
    assert checks["text_primary"]["status"] == checks["embedding"]["status"] == "DISABLED"


@pytest.mark.asyncio
async def test_dimension_conflict_is_a_failure(configured):
    configured.embedding_dim = 1536
    report = await live.verify_services()
    assert report["failures"] == 1
    assert by_name(report)["knowledge_dimensions"]["code"] == "dimensions_mismatch"


@pytest.mark.asyncio
async def test_unselected_provider_requires_explicit_standby_option(configured):
    configured.llm_fallback_provider = "none"
    configured.deepseek_api_key = "secret"
    assert "text_standby_deepseek" not in by_name(await live.verify_services())
    assert by_name(await live.verify_services(include_standby=True))["text_standby_deepseek"]["status"] == "PASS"


@pytest.mark.asyncio
async def test_failed_primary_is_not_hidden_by_passing_fallback(configured, monkeypatch):
    async def text(provider):
        if provider == "ark":
            raise RuntimeError("secret-api-key business text https://host?key=private-key")
        return {"provider": provider}
    monkeypatch.setattr(live, "text_probe", text)
    report = await live.verify_services()
    checks = by_name(report)
    assert report["failures"] == 1
    assert checks["text_primary"]["status"] == "FAIL"
    assert checks["text_fallback"]["status"] == "PASS"
    for secret in ("secret-api-key", "business text", "private-key", "https://host"):
        assert secret not in json.dumps(report)


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant,scope", [("another-tenant", True), ("local", False)])
async def test_wecom_scope_must_exist_and_match_identity(configured, monkeypatch, tenant, scope):
    configured.wecom_tenant_id = tenant
    original = live.database_snapshot
    async def database(settings):
        return {**await original(settings), "wecom_scope_exists": scope}
    monkeypatch.setattr(live, "database_snapshot", database)
    assert by_name(await live.verify_services())["wecom_configuration"]["status"] == "FAIL"


@pytest.mark.asyncio
async def test_probe_failure_does_not_skip_other_checks(configured, monkeypatch):
    async def database(_):
        raise RuntimeError("postgresql://user:secret@host/private")
    monkeypatch.setattr(live, "database_snapshot", database)
    report = await live.verify_services()
    checks = by_name(report)
    assert checks["database"]["status"] == "FAIL"
    assert checks["wecom_configuration"]["status"] == "FAIL"
    assert checks["text_primary"]["status"] == checks["smtp_authentication"]["status"] == "PASS"
    assert "postgresql" not in json.dumps(report)


def test_smtp_performs_tls_and_auth_without_message_commands(configured, monkeypatch):
    events = []
    class SMTP:
        def __init__(self, *args, **kwargs):
            events.append("connect")
        def __enter__(self):
            return self
        def __exit__(self, *args):
            events.append("quit")
        def ehlo(self):
            events.append("ehlo")
            return 250, b"OK"
        def starttls(self, *, context):
            assert context.check_hostname
            events.append("tls")
        def login(self, username, password):
            events.append("auth")
        def mail(self, *_):
            pytest.fail("MAIL forbidden")
        def rcpt(self, *_):
            pytest.fail("RCPT forbidden")
        def data(self, *_):
            pytest.fail("DATA forbidden")
        def sendmail(self, *_):
            pytest.fail("sendmail forbidden")
    # The fixture stubs this function; restore its original implementation below.
    monkeypatch.setattr(live.smtplib, "SMTP", SMTP)
    ORIGINAL_SMTP_AUTH(configured)
    assert events == ["connect", "ehlo", "tls", "ehlo", "auth", "quit"]


ORIGINAL_SMTP_AUTH = live.smtp_authenticate
ORIGINAL_DATABASE_SNAPSHOT = live.database_snapshot
ORIGINAL_TEXT_PROBE = live.text_probe


def test_smtp_refuses_plaintext_authentication(configured, monkeypatch):
    configured.smtp_starttls = False
    monkeypatch.setattr(live.smtplib, "SMTP", lambda *_args, **_kwargs: pytest.fail("plaintext connection"))
    with pytest.raises(ValueError, match="TLS"):
        ORIGINAL_SMTP_AUTH(configured)


@pytest.mark.asyncio
async def test_database_uses_read_only_transaction_and_disposes_engine(configured, monkeypatch):
    statements = []
    closed = []
    class Connection:
        @asynccontextmanager
        async def begin(self):
            yield
        async def execute(self, statement, parameters=None):
            sql = str(statement)
            statements.append(sql)
            result = MagicMock()
            if "format_type" in sql:
                result.scalar_one.return_value = "vector(1024)"
            elif "count(*)" in sql:
                result.mappings.return_value.one.return_value = {"chunks": 3, "missing": 0, "mismatched": 0}
            elif "EXISTS" in sql:
                assert parameters == {"tenant": "local", "department": "department"}
                assert "enabled = true" in sql
                result.scalar_one.return_value = True
            return result
        async def run_sync(self, callback):
            assert callback is live.assert_schema_current
            statements.append("SCHEMA_CHECK")
    class Engine:
        @asynccontextmanager
        async def connect(self):
            yield Connection()
        async def dispose(self):
            closed.append(True)
    monkeypatch.setattr(live, "create_async_engine", lambda *_args, **_kwargs: Engine())
    snapshot = await ORIGINAL_DATABASE_SNAPSHOT(configured)
    assert statements[0] == "SET TRANSACTION READ ONLY"
    assert all(sql.startswith(("SET ", "SELECT ", "SCHEMA_CHECK")) for sql in statements)
    assert snapshot["wecom_scope_exists"] is True
    assert closed == [True]


@pytest.mark.asyncio
async def test_text_probe_requires_bounded_validated_structured_response(monkeypatch):
    calls = []
    class Client:
        last_usage = {"total_tokens": 10}
        def __init__(self, provider):
            assert provider == "deepseek"
        async def structured(self, messages, schema, **kwargs):
            calls.append((messages, kwargs))
            assert schema.model_validate({"reply": "OK"}).reply == "OK"
            with pytest.raises(ValueError):
                schema.model_validate({"reply": "invalid"})
    monkeypatch.setattr(live, "CompatibleLLM", Client)
    assert await ORIGINAL_TEXT_PROBE("deepseek") == {
        "provider": "deepseek", "structured_output": True, "usage": {"total_tokens": 10}}
    assert len(calls) == 1
    assert calls[0][1] == {"max_tokens": 128, "timeout_seconds": 30}


@pytest.mark.asyncio
async def test_authentication_failure_uses_safe_category(configured, monkeypatch):
    def smtp(_):
        raise live.smtplib.SMTPAuthenticationError(535, b"private-key user@example.test")
    monkeypatch.setattr(live, "smtp_authenticate", smtp)
    report = await live.verify_services()
    assert by_name(report)["smtp_authentication"]["code"] == "authentication_rejected"
    assert "private-key" not in json.dumps(report)


@pytest.mark.parametrize('reply,status', [(b'stream: OK\0', 'PASS'), (b'engine error\0', 'FAIL')])
async def test_scanner_preflight_uses_clean_stream_without_claiming_detection(configured, reply, status):
    from tests.scanner_support import scanner_server
    async with scanner_server(reply) as (port, requests):
        configured.clamd_host, configured.clamd_port = '127.0.0.1', port
        report = await live.verify_services()
    checks = by_name(report)
    assert checks['attachment_scanner']['status'] == status
    assert checks['attachment_detection']['status'] == 'UNVERIFIED'
    assert len(requests) == 1 and b'EICAR-' not in requests[0]['content']
    assert report['failures'] == (0 if status == 'PASS' else 1)
