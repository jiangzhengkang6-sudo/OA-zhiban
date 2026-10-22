"""Atomic claim and reconciliation of high-impact writes.

Callers MUST commit the claim transaction BEFORE external side effects, then
complete in a second transaction. A pending/unknown claim is never re-executed
until the external system is reconciled with the SAME key.
"""
import hashlib
import json
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from ..core.enums import ErrorCode
from ..core.errors import AppException
from ..models.idempotency_record import IdempotencyRecord


def payload_digest(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _scope(envelope) -> dict:
    return {name: getattr(envelope, name) for name in
        ("tenant_id", "actor_id", "resource_type", "resource_id", "idempotency_key")}


async def claim(session: AsyncSession, envelope) -> tuple[IdempotencyRecord, bool]:
    """Acquire unique command scope; never replay an in-flight external write."""
    scope = _scope(envelope)
    stmt = insert(IdempotencyRecord).values(
        id=uuid4(), command_id=envelope.command_id, **scope,
        payload_hash=envelope.payload_hash, trace_id=envelope.trace_id,
        status="PENDING",
    ).on_conflict_do_nothing(constraint="uq_idempotency_scope").returning(IdempotencyRecord.id)
    created = (await session.execute(stmt)).scalar_one_or_none()
    record = (await session.scalars(select(IdempotencyRecord).filter_by(**scope).with_for_update())).one()
    if record.payload_hash != envelope.payload_hash:
        raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "相同幂等键对应不同业务内容", http_status=409)
    if created is None and record.status == "FAILED" and record.result == {"not_called": True}:
        # This is the only provably safe re-claim: the external function was
        # never entered. UNKNOWN/PENDING still require authoritative lookup.
        record.status = "PENDING"
        record.result = None
        await session.flush()
        return record, True
    if created is None and record.status != "SUCCEEDED":
        raise AppException(ErrorCode.INVALID_STATE, "写入结果尚未确认，须使用原幂等键先对账", http_status=409)
    return record, created is not None


async def complete(session: AsyncSession, record: IdempotencyRecord, result: dict) -> None:
    if record.status != "PENDING":
        raise AppException(ErrorCode.INVALID_STATE, "命令状态不允许完成", http_status=409)
    record.status = "SUCCEEDED"
    record.result = result
    await session.flush()


async def resolve_unknown(session: AsyncSession, envelope, authoritative_result: dict, external_request_id: str):
    """Only a verified external result may complete an uncertain write."""
    record = (await session.scalars(select(IdempotencyRecord).filter_by(**_scope(envelope)).with_for_update())).one()
    if record.payload_hash != envelope.payload_hash or record.status not in {"PENDING", "UNKNOWN"}:
        raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, "命令无法对账", http_status=409)
    if not external_request_id:
        raise AppException(ErrorCode.BAD_REQUEST, "缺少外部请求编号", http_status=400)
    record.status = "SUCCEEDED"
    record.result = authoritative_result
    record.external_request_id = external_request_id
    await session.flush()
    return record
