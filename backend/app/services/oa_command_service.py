"""Serialized, idempotent, atomic business commands. Callers own final commit."""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import select, text
from ..core.errors import AppException, ErrorCode
from ..core.context import get_trace_id
from ..models.identity import OAUser
from ..models.oa_workflow import OAWorkflowOperation, OAWorkflowEvent, OAWorkflowOutbox
from .identity_service import lock_tenant
from .oa_access_service import OAAccessTarget, authorize_oa, builtin_actor


def _json_default(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f')
    raise TypeError('Unsupported command value')


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'),
        default=_json_default).encode()).hexdigest()


@dataclass
class OACommand:
    kind: str
    target_id: str
    target_version: str
    operation_id: str
    payload: dict
    resource: str
    target: OAAccessTarget
    applicant_id: str | None = None
    reauthorize: object = None
    trace_id: str | None = None


@dataclass
class CommandOutcome:
    result: dict
    replayed: bool = False
    current_revision: int | None = None
    allowed_actions: list[str] = field(default_factory=list)
    recipients: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)
    recipient_access: dict = field(default_factory=dict)
    changes: dict = field(default_factory=dict)

    def response(self):
        return dict(result=self.result, replayed=self.replayed, current_revision=self.current_revision,
                    allowed_actions=self.allowed_actions)


async def persist_events(db, actor, command, operation, outcome):
    event = OAWorkflowEvent(id=str(uuid4()), tenant_id=actor.tenant_id, operation_id=operation.id,
        actor_id=actor.user_id, event_key=operation.id, action=command.kind, target_id=command.target_id,
        detail=outcome.detail, trace_id=(command.trace_id or get_trace_id() or str(uuid4()))[:128],
        target_version=command.target_version, changes=outcome.changes)
    db.add(event)
    await db.flush()
    for user_id in sorted(set(outcome.recipients)):
        user = await db.scalar(select(OAUser).where(OAUser.id == user_id, OAUser.tenant_id == actor.tenant_id,
                                                    OAUser.status == 'active'))
        if user:
            from .identity_service import current_identity
            recipient = await current_identity(db, user)
            resource, target = outcome.recipient_access.get(user_id, (command.resource, command.target))
            try:
                await authorize_oa(db, recipient, resource, 'read', target=target)
            except AppException:
                continue
            db.add(OAWorkflowOutbox(tenant_id=actor.tenant_id, event_id=event.id, recipient_id=user.id,
                status='PENDING', payload=dict(action=command.kind, target_id=command.target_id)))
    await db.flush()


async def run_command(db, actor, command, handler):
    actor = await builtin_actor(db, actor)
    await lock_tenant(db, actor.tenant_id)
    actor = (await authorize_oa(db, actor, command.resource, 'write', target=command.target)).actor
    if command.applicant_id:
        await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                         {'key': 'oa-applicant:' + actor.tenant_id + ':' + command.applicant_id})
    if command.reauthorize:
        await command.reauthorize()
    digest = canonical_hash(command.payload)
    existing = await db.scalar(select(OAWorkflowOperation).where(OAWorkflowOperation.tenant_id == actor.tenant_id,
        OAWorkflowOperation.kind == command.kind, OAWorkflowOperation.target_id == command.target_id,
        OAWorkflowOperation.target_version == command.target_version, OAWorkflowOperation.operation_id == command.operation_id))
    if existing:
        if existing.actor_id != actor.user_id or existing.payload_hash != digest:
            raise AppException(ErrorCode.IDEMPOTENCY_CONFLICT, '操作编号已用于不同内容', http_status=409)
        return CommandOutcome(result=existing.result, replayed=True, current_revision=existing.result.get('revision'))
    # Savepoint also protects direct service callers that catch a domain error.
    async with db.begin_nested():
        operation = OAWorkflowOperation(id=str(uuid4()), tenant_id=actor.tenant_id, actor_id=actor.user_id,
            kind=command.kind, target_id=command.target_id, target_version=command.target_version,
            operation_id=command.operation_id, payload_hash=digest, result={})
        db.add(operation)
        await db.flush()
        outcome = await handler(operation)
        operation.result = outcome.result
        outcome.current_revision = outcome.result.get('revision')
        await persist_events(db, actor, command, operation, outcome)
        await builtin_actor(db, actor)
    return outcome
