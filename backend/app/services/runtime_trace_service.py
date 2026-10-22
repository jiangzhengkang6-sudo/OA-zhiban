"""Runtime span and model usage aggregation for operations views."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.model_usage import ModelUsage
from ..models.runtime_span import RuntimeSpan
from ..models.model_usage import ModelUsage


async def record_span(
    session: AsyncSession,
    *,
    tenant_id: str,
    trace_id: str,
    node_name: str,
    tool_name: Optional[str],
    started_at: datetime,
    finished_at: datetime,
    status: str,
    error_code: Optional[str] = None,
    thread_id: Optional[UUID] = None,
    run_id: Optional[UUID] = None,
) -> None:
    """Persist one span defensively; callers decide transaction boundaries."""
    duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    session.add(RuntimeSpan(
        tenant_id=tenant_id, trace_id=trace_id or "unknown", run_id=run_id or uuid4(),
        thread_id=thread_id, node_name=node_name, tool_name=tool_name,
        started_at=started_at, finished_at=finished_at, duration_ms=duration_ms,
        status=status, error_code=error_code,
    ))


async def record_model_usage(
    session: AsyncSession,
    *,
    tenant_id: str,
    trace_id: str,
    provider: str,
    model_name: str,
    run_id: Optional[UUID] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
) -> None:
    """Persist usage and explicitly mark providers that omit token metadata."""
    session.add(ModelUsage(
        tenant_id=tenant_id, trace_id=trace_id or "unknown", run_id=run_id or uuid4(),
        provider=provider, model_name=model_name, input_tokens=input_tokens,
        output_tokens=output_tokens, total_tokens=total_tokens,
        usage_missing=total_tokens is None,
    ))


async def record_model_attempts(session: AsyncSession, *, tenant_id: str, trace_id: str,
                                usage: dict, provider: str, model_name: str) -> None:
    """Keep fallback usage attributed to the provider that received each request."""
    attempts = usage.get("attempts") or [{"provider": provider, "model": model_name, "usage": usage}]
    for attempt in attempts:
        tokens = attempt.get("usage") or {}
        await record_model_usage(session, tenant_id=tenant_id, trace_id=trace_id,
            provider=attempt["provider"], model_name=attempt["model"],
            input_tokens=tokens.get("prompt_tokens"), output_tokens=tokens.get("completion_tokens"),
            total_tokens=tokens.get("total_tokens"))


async def metrics(session: AsyncSession, *, tenant_id: str, trace_id: Optional[str] = None) -> dict:
    span_conditions = [RuntimeSpan.tenant_id == tenant_id]
    usage_conditions = [ModelUsage.tenant_id == tenant_id]
    if trace_id:
        span_conditions.append(RuntimeSpan.trace_id == trace_id)
        usage_conditions.append(ModelUsage.trace_id == trace_id)
    span_count = int((await session.execute(select(func.count()).select_from(RuntimeSpan).where(*span_conditions))).scalar_one())
    error_count = int((await session.execute(select(func.count()).select_from(RuntimeSpan).where(*span_conditions, RuntimeSpan.status.in_(["error", "failed"])))).scalar_one())
    duration = (await session.execute(select(func.avg(RuntimeSpan.duration_ms), func.sum(RuntimeSpan.duration_ms)).where(*span_conditions))).one()
    usage_rows = list((await session.execute(select(ModelUsage).where(*usage_conditions))).scalars().all())
    known_tokens = [row.total_tokens for row in usage_rows if row.total_tokens is not None and not row.usage_missing]
    return {
        "span_count": span_count,
        "error_count": error_count,
        "avg_duration_ms": float(duration[0]) if duration[0] is not None else None,
        "total_duration_ms": int(duration[1]) if duration[1] is not None else 0,
        "usage_count": len(usage_rows),
        "usage_missing_count": sum(1 for row in usage_rows if row.usage_missing or row.total_tokens is None),
        "total_tokens": sum(known_tokens) if known_tokens else None,
    }


async def trace_detail(session: AsyncSession, *, tenant_id: str, trace_id: str) -> dict:
    spans = list((await session.execute(select(RuntimeSpan).where(RuntimeSpan.tenant_id == tenant_id, RuntimeSpan.trace_id == trace_id).order_by(RuntimeSpan.started_at))).scalars().all())
    usage = list((await session.execute(select(ModelUsage).where(ModelUsage.tenant_id == tenant_id, ModelUsage.trace_id == trace_id).order_by(ModelUsage.created_at))).scalars().all())
    return {
        "trace_id": trace_id,
        "spans": [{"id": str(item.id), "run_id": str(item.run_id), "node_name": item.node_name, "tool_name": item.tool_name, "duration_ms": item.duration_ms, "status": item.status, "error_code": item.error_code, "started_at": item.started_at, "finished_at": item.finished_at} for item in spans],
        "model_usage": [{"id": str(item.id), "run_id": str(item.run_id), "provider": item.provider, "model_name": item.model_name, "input_tokens": item.input_tokens, "output_tokens": item.output_tokens, "total_tokens": item.total_tokens, "usage_missing": item.usage_missing} for item in usage],
    }
