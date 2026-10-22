"""Bounded live probes without app lifespan, queue dispatch or business writes."""
import asyncio
import smtplib
import ssl
from datetime import datetime, timezone
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ..core.config import get_settings
from ..db.migrations import assert_schema_current, validate_runtime_configuration
from ..llm.compatible import CompatibleLLM
from ..llm.embedding import ArkEmbedding
from ..providers.wecom import destination


async def database_snapshot(settings):
    engine = create_async_engine(settings.database_url, connect_args={"timeout": 10},
                                 echo=False, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                await connection.execute(text("SET LOCAL statement_timeout = '10s'"))
                await connection.run_sync(assert_schema_current)
                column_type = (await connection.execute(text(
                    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                    "WHERE attrelid = 'knowledge_chunk'::regclass AND attname = 'embedding'"
                ))).scalar_one()
                counts = (await connection.execute(text(
                    "SELECT count(*) AS chunks, count(*) FILTER (WHERE embedding IS NULL) AS missing, "
                    "count(*) FILTER (WHERE embedding IS NOT NULL AND "
                    "vector_dims(embedding) != :dimension) AS mismatched FROM knowledge_chunk"
                ), {"dimension": settings.embedding_dim})).mappings().one()
                scope_exists = False
                if settings.wecom_enabled:
                    scope_exists = bool((await connection.execute(text(
                        "SELECT EXISTS(SELECT 1 FROM oa_department WHERE tenant_id = :tenant "
                        "AND id = :department AND enabled = true)"
                    ), {"tenant": settings.wecom_tenant_id,
                        "department": settings.wecom_department_id})).scalar_one())
                return {"schema_current": True, "vector_type": column_type, **dict(counts),
                        "wecom_scope_exists": scope_exists}
    finally:
        await engine.dispose()


def smtp_authenticate(settings):
    """TLS and AUTH only. Never issue MAIL, RCPT or DATA."""
    if not all((settings.smtp_host.strip(), settings.smtp_from.strip(),
                settings.smtp_username.strip(), settings.smtp_password)):
        raise ValueError("incomplete SMTP configuration")
    if not settings.smtp_starttls:
        raise ValueError("TLS required before authentication")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port,
                      timeout=settings.smtp_timeout_seconds) as client:
        if client.ehlo()[0] != 250:
            raise RuntimeError("SMTP greeting rejected")
        client.starttls(context=ssl.create_default_context())
        if client.ehlo()[0] != 250:
            raise RuntimeError("SMTP TLS greeting rejected")
        client.login(settings.smtp_username, settings.smtp_password)


class TextProbeResult(BaseModel):
    reply: Literal["OK"]


async def text_probe(provider):
    client = CompatibleLLM(provider)
    await client.structured([{"role": "user", "content": 'Return {"reply":"OK"}.'}],
                            TextProbeResult, max_tokens=128, timeout_seconds=30)
    # Provider responses and endpoint/model identifiers are deliberately omitted.
    return {"provider": provider, "structured_output": True, "usage": client.last_usage}


async def embedding_probe(settings):
    vectors = await ArkEmbedding().embed(["Office knowledge service connectivity check."])
    if len(vectors) != 1 or len(vectors[0]) != settings.embedding_dim:
        raise RuntimeError("embedding dimension mismatch")
    return {"provider": "ark", "dimension": len(vectors[0])}


async def verify_services(*, include_standby=False):
    settings = get_settings()
    checks = []

    def record(name, status, code, **details):
        checks.append({"check": name, "status": status, "code": code, **details})

    async def probe(name, operation):
        started = monotonic()
        try:
            details = await operation()
        except Exception as exc:
            # Even exception names/messages can contain server-controlled secrets.
            code = "probe_failed"
            if isinstance(exc, smtplib.SMTPAuthenticationError):
                code = "authentication_rejected"
            elif isinstance(exc, ssl.SSLError):
                code = "tls_failed"
            elif isinstance(exc, TimeoutError):
                code = "timeout"
            record(name, "FAIL", code, elapsed_ms=round((monotonic()-started)*1000))
            return None
        record(name, "PASS", "verified", elapsed_ms=round((monotonic()-started)*1000), **(details or {}))
        return details

    async def runtime_config():
        await asyncio.to_thread(validate_runtime_configuration, settings)
        return {"oa_provider": settings.oa_provider, "auth_provider": settings.auth_provider}

    await probe("runtime_configuration", runtime_config)
    if settings.oa_provider == "mock" or settings.auth_provider == "mock":
        record("formal_identity", "MOCK", "mock_identity_or_oa")
    snapshot = await probe("database", lambda: database_snapshot(settings))
    if snapshot:
        aligned = (snapshot["vector_type"] == f"vector({settings.embedding_dim})"
                   and snapshot["mismatched"] == 0)
        record("knowledge_dimensions", "PASS" if aligned else "FAIL",
               "dimensions_match" if aligned else "dimensions_mismatch",
               configured_dimension=settings.embedding_dim)
        record("knowledge_vector_provenance", "UNVERIFIED", "stored_model_not_recorded")
    if not settings.ai_enabled:
        record("text_primary", "DISABLED", "ai_disabled")
        record("embedding", "DISABLED", "ai_disabled")
    else:
        providers = [("text_primary", settings.llm_provider)]
        if settings.llm_fallback_provider not in {"none", settings.llm_provider}:
            providers.append(("text_fallback", settings.llm_fallback_provider))
        if include_standby:
            selected = {provider for _, provider in providers}
            providers.extend((f"text_standby_{provider}", provider) for provider in ("deepseek", "ark")
                             if provider not in selected and getattr(settings, f"{provider}_api_key").strip())
        for name, provider in providers:
            if provider == "mock":
                record(name, "MOCK", "mock_text_provider")
            else:
                await probe(name, lambda provider=provider: text_probe(provider))
        if settings.embedding_provider == "mock":
            record("embedding", "MOCK", "mock_embedding_provider")
        else:
            await probe("embedding", lambda: embedding_probe(settings))
    if settings.smtp_enabled:
        async def smtp_probe():
            await asyncio.to_thread(smtp_authenticate, settings)
            return {"tls": True, "authenticated": True, "message_sent": False}
        await probe("smtp_authentication", smtp_probe)
        record("smtp_delivery", "UNVERIFIED", "no_message_sent")
    else:
        record("smtp_authentication", "DISABLED", "smtp_disabled")
    if settings.wecom_enabled:
        configured = bool(destination(settings, settings.auth_tenant_id, settings.wecom_department_id))
        scope_exists = snapshot is not None and snapshot["wecom_scope_exists"]
        record("wecom_configuration", "PASS" if configured and scope_exists else "FAIL",
               "configuration_and_scope_valid" if configured and scope_exists else "invalid_configuration_or_scope")
        record("wecom_delivery", "UNVERIFIED", "no_webhook_posted")
    else:
        record("wecom_configuration", "DISABLED", "wecom_disabled")
    record("attachment_scanner", "UNVERIFIED" if settings.clamd_host else "DISABLED",
           "scanner_not_probed" if settings.clamd_host else "scanner_not_configured")
    try:
        url = urlsplit(settings.notification_app_url)
        remote_url = url.scheme == "https" and url.hostname not in {None, "localhost", "127.0.0.1", "::1"}
    except ValueError:
        remote_url = False
    record("notification_public_url", "UNVERIFIED", "https_url_not_probed" if remote_url else "public_https_required")
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "checks": checks,
            "failures": sum(item["status"] == "FAIL" for item in checks),
            "production_acceptance": False,
            "boundary": "Read-only DB; synthetic model calls; SMTP AUTH only; no queue dispatch or notification delivery."}
