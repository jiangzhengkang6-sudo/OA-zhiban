"""Trusted bindings; callers authorize and own the domain transaction."""
from datetime import datetime,timedelta,timezone
from uuid import UUID
from sqlalchemy import select
from ..models.agent_thread import AgentThread
from ..models.oa_bridge import OABridgeConfirmation,OABridgeResult
from .oa_access_service import builtin_actor,denied,invalid
from .oa_command_service import canonical_hash


async def validate_thread(db,actor,thread_id):
    if thread_id is None: return
    try: key=UUID(thread_id)
    except (ValueError,TypeError): raise invalid('会话编号无效') from None
    thread=await db.scalar(select(AgentThread).where(AgentThread.id==key,AgentThread.tenant_id==actor.tenant_id,
        AgentThread.user_id==actor.user_id).execution_options(populate_existing=True))
    if thread is None: raise denied()


async def issue(db,actor,*,thread_id,action,object_id,object_version,payload):
    actor=await builtin_actor(db,actor)
    await validate_thread(db,actor,thread_id)
    row=OABridgeConfirmation(tenant_id=actor.tenant_id,actor_id=actor.user_id,thread_id=thread_id,action=action,
        object_id=object_id,object_version=str(object_version),payload_hash=canonical_hash(payload),
        expires_at=datetime.now(timezone.utc)+timedelta(minutes=10))
    db.add(row)
    await db.flush()
    return dict(confirmation_id=row.id,expires_at=row.expires_at.isoformat())


async def binding(db,actor,confirmation_id,*,thread_id,action,object_id,object_version,payload,lock=False):
    actor=await builtin_actor(db,actor)
    await validate_thread(db,actor,thread_id)
    query=select(OABridgeConfirmation).where(OABridgeConfirmation.id==confirmation_id,
        OABridgeConfirmation.tenant_id==actor.tenant_id,OABridgeConfirmation.actor_id==actor.user_id).execution_options(populate_existing=True)
    row=await db.scalar(query.with_for_update() if lock else query)
    if row is None or (row.thread_id,row.action,row.object_id,row.object_version,row.payload_hash)!=(
            thread_id,action,object_id,str(object_version),canonical_hash(payload)):
        raise invalid('确认内容不匹配，请重新核对并确认')
    return row


async def consume(db,actor,confirmation_id,operation_id,**binding_values):
    row=await binding(db,actor,confirmation_id,lock=True,**binding_values)
    if row.consumed_operation_id or row.expires_at<=datetime.now(timezone.utc):
        raise invalid('确认已使用或已过期，请重新确认')
    row.consumed_operation_id=operation_id
    await db.flush()


async def record_result(db,actor,*,method,original_key,target_id,target_version,operation_id,result):
    db.add(OABridgeResult(tenant_id=actor.tenant_id,actor_id=actor.user_id,method=method,original_key=original_key,
        target_id=target_id,target_version=str(target_version),operation_id=operation_id,
        result={key:value for key,value in result.items() if key in {'id','state','revision','merged'}}))
    await db.flush()
