"""Explicit, non-transitive delegation; evaluate current identity on every use."""
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import select, or_, and_
from ..models.identity import OAUser, OAMembership
from ..models.oa_delegation import OAApprovalDelegation
from .identity_service import utcnow
from .oa_access_service import builtin_actor, authorize_oa, OAAccessTarget, tenant_row, denied, invalid, revision_conflict
from .oa_command_service import OACommand, CommandOutcome, run_command
from . import oa_workflow_service as workflows


async def authority(db, actor, action='read'):
    actor = await builtin_actor(db, actor)
    await authorize_oa(db, actor, 'approval', action, target=OAAccessTarget(actor.tenant_id, actor.user_id))
    return actor


async def qualified(db, tenant, owner_id, delegate_id, department_id):
    for uid in (owner_id, delegate_id):
        if not await workflows.eligible_user(db, tenant, uid, '', approval=True):
            return False
        membership = await db.get(OAMembership, (tenant, uid), populate_existing=True)
        if not membership or membership.department_id != department_id:
            return False
    return True


async def projection(db, row):
    names = dict((await db.execute(select(OAUser.id, OAUser.display_name).where(
        OAUser.tenant_id == row.tenant_id, OAUser.id.in_([row.delegator_id, row.delegate_id])))).all())
    now = utcnow()
    state = 'REVOKED' if row.revoked_at else 'EXPIRED' if now >= row.ends_at else 'SCHEDULED' if now < row.starts_at else 'ACTIVE'
    if state in {'SCHEDULED', 'ACTIVE'} and not await qualified(db, row.tenant_id, row.delegator_id, row.delegate_id, row.department_id):
        state = 'INELIGIBLE'
    return dict(id=row.id, delegator_id=row.delegator_id, delegate_id=row.delegate_id,
        delegator_name=names.get(row.delegator_id, '原审批人'), delegate_name=names.get(row.delegate_id, '受托人'),
        scene=row.scene, starts_at=row.starts_at.isoformat(), ends_at=row.ends_at.isoformat(),
        revoked_at=row.revoked_at.isoformat() if row.revoked_at else None, reason=row.reason,
        revision=row.revision, state=state)


async def list_items(db, actor):
    actor = await authority(db, actor)
    rows = (await db.scalars(select(OAApprovalDelegation).where(OAApprovalDelegation.tenant_id == actor.tenant_id,
        or_(OAApprovalDelegation.delegator_id == actor.user_id, OAApprovalDelegation.delegate_id == actor.user_id))
        .order_by(OAApprovalDelegation.created_at.desc()))).all()
    return [await projection(db, row) for row in rows]


async def candidates(db, actor):
    actor = await authority(db, actor, 'write')
    if not actor.depts:
        return []
    users = (await db.scalars(select(OAUser).join(OAMembership, and_(
        OAMembership.tenant_id == OAUser.tenant_id, OAMembership.user_id == OAUser.id)).where(
        OAUser.tenant_id == actor.tenant_id, OAMembership.department_id == actor.depts[0], OAUser.id != actor.user_id,
        OAUser.status == 'active').order_by(OAUser.display_name, OAUser.id))).all()
    return [dict(id=u.id, name=u.display_name) for u in users
        if await qualified(db, actor.tenant_id, actor.user_id, u.id, actor.depts[0])]


async def create(db, actor, payload):
    actor = await authority(db, actor, 'write')
    identifier = str(uuid5(NAMESPACE_URL, actor.tenant_id + ':' + actor.user_id + ':delegation:' + payload.operation_id))
    async def perform(operation):
        if payload.delegate_id == actor.user_id or not actor.depts or payload.ends_at <= utcnow():
            raise invalid('受托人不能是本人，且结束时间必须晚于当前时间')
        if not await qualified(db, actor.tenant_id, actor.user_id, payload.delegate_id, actor.depts[0]):
            raise invalid('双方须为同部门有效成员，并具备审批读写资格')
        overlap = await db.scalar(select(OAApprovalDelegation.id).where(
            OAApprovalDelegation.tenant_id == actor.tenant_id, OAApprovalDelegation.scene == payload.scene,
            OAApprovalDelegation.revoked_at.is_(None), OAApprovalDelegation.starts_at < payload.ends_at,
            OAApprovalDelegation.ends_at > payload.starts_at,
            or_(OAApprovalDelegation.delegator_id == actor.user_id,
                OAApprovalDelegation.delegate_id == actor.user_id,
                OAApprovalDelegation.delegator_id == payload.delegate_id,
                OAApprovalDelegation.delegate_id == payload.delegate_id)))
        if overlap:
            raise invalid('该时段已有委托，或会形成链式委托，请先调整或撤销')
        row = OAApprovalDelegation(id=identifier, tenant_id=actor.tenant_id, delegator_id=actor.user_id,
            delegate_id=payload.delegate_id, department_id=actor.depts[0], scene=payload.scene,
            starts_at=payload.starts_at, ends_at=payload.ends_at, reason=payload.reason)
        db.add(row)
        await db.flush()
        return CommandOutcome(result=await projection(db, row), detail=dict(scene=row.scene,
            delegate_id=row.delegate_id, starts_at=row.starts_at.isoformat(), ends_at=row.ends_at.isoformat(), reason=row.reason))
    return await run_command(db, actor, OACommand(kind='approval.delegation.create', target_id=identifier,
        target_version='0', operation_id=payload.operation_id, payload=payload.model_dump(mode='json'),
        resource='approval', target=OAAccessTarget(actor.tenant_id, actor.user_id)), perform)


async def revoke(db, actor, identifier, payload):
    actor = await authority(db, actor, 'write')
    row = await tenant_row(db, OAApprovalDelegation, actor, identifier)
    if row.delegator_id != actor.user_id:
        raise denied()
    async def perform(operation):
        row = await tenant_row(db, OAApprovalDelegation, actor, identifier, lock=True)
        if row.revision != payload.expected_revision:
            raise revision_conflict()
        if row.revoked_at:
            raise invalid('该委托已撤销')
        row.revoked_at, row.revision = utcnow(), row.revision + 1
        return CommandOutcome(result=await projection(db, row), detail=dict(delegate_id=row.delegate_id, scene=row.scene))
    return await run_command(db, actor, OACommand(kind='approval.delegation.revoke', target_id=identifier,
        target_version=str(payload.expected_revision), operation_id=payload.operation_id,
        payload=payload.model_dump(), resource='approval', target=OAAccessTarget(actor.tenant_id, actor.user_id)), perform)


async def for_seat(db, actor, subject, instance, seat, seats):
    if seat.substituted or seat.escalated or actor.user_id == subject.applicant_id:
        return None
    if any(other.effective_user_id == actor.user_id for other in seats):
        return None
    now = utcnow()
    row = await db.scalar(select(OAApprovalDelegation).where(OAApprovalDelegation.tenant_id == actor.tenant_id,
        OAApprovalDelegation.delegator_id == seat.effective_user_id, OAApprovalDelegation.delegate_id == actor.user_id,
        OAApprovalDelegation.scene == instance.scene, OAApprovalDelegation.revoked_at.is_(None),
        OAApprovalDelegation.starts_at <= now, OAApprovalDelegation.ends_at > now))
    if row and await qualified(db, actor.tenant_id, row.delegator_id, actor.user_id, row.department_id):
        return row
    return None
