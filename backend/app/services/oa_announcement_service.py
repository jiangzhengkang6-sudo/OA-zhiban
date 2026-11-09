"""Versioned publication; current department and permission checked on every read."""
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from ..core.errors import not_found
from ..models.oa_announcement import OAAnnouncement, OAAnnouncementRead
from ..models.identity import OADepartment
from .authorization_service import require_permission
from .identity_service import utcnow, lock_tenant
from .oa_access_service import (builtin_actor, OAAccessTarget, tenant_row,
    department_permission, invalid, revision_conflict)
from .oa_command_service import OACommand, CommandOutcome, run_command
from .oa_scope_service import record_audit


def manageable(actor, row):
    return row.department_id in actor.depts and department_permission(actor, 'announcement', 'write')


async def audience(db, actor):
    actor = await builtin_actor(db, actor)
    require_permission(actor, 'announcement', 'read')
    departments = list((await db.scalars(select(OADepartment.id).where(
        OADepartment.tenant_id == actor.tenant_id, OADepartment.id.in_(actor.depts),
        OADepartment.enabled.is_(True)))).all())
    return actor, departments


def view(row, receipt, actor):
    return dict(id=row.id, department_id=row.department_id, author_id=row.author_id,
        title=row.title, body=row.body, state=row.state, revision=row.revision,
        published_at=row.published_at.isoformat() if row.published_at else None,
        withdrawn_at=row.withdrawn_at.isoformat() if row.withdrawn_at else None,
        read_at=receipt.read_at.isoformat() if receipt else None,
        can_manage=manageable(actor, row))


async def access(db, actor, announcement_id, *, lock=False):
    actor, departments = await audience(db, actor)
    row = await tenant_row(db, OAAnnouncement, actor, announcement_id, lock=lock)
    if row.department_id not in departments or row.state != 'PUBLISHED' and not manageable(actor, row):
        raise not_found('公告不存在或不可访问')
    return actor, row


async def receipt_for(db, actor, row):
    return await db.scalar(select(OAAnnouncementRead).where(OAAnnouncementRead.tenant_id == actor.tenant_id,
        OAAnnouncementRead.announcement_id == row.id, OAAnnouncementRead.reader_id == actor.user_id))


async def list_items(db, actor, *, manage=False):
    actor, departments = await audience(db, actor)
    if manage:
        require_permission(actor, 'announcement', 'write')
        if not department_permission(actor, 'announcement', 'write'):
            departments = []
    query = select(OAAnnouncement, OAAnnouncementRead).outerjoin(OAAnnouncementRead,
        (OAAnnouncementRead.tenant_id == OAAnnouncement.tenant_id) &
        (OAAnnouncementRead.announcement_id == OAAnnouncement.id) &
        (OAAnnouncementRead.reader_id == actor.user_id)).where(
        OAAnnouncement.tenant_id == actor.tenant_id, OAAnnouncement.department_id.in_(departments))
    if not manage:
        query = query.where(OAAnnouncement.state == 'PUBLISHED')
    rows = (await db.execute(query.order_by(OAAnnouncement.created_at.desc(), OAAnnouncement.id))).all()
    return [view(row, receipt, actor) for row, receipt in rows]


async def detail(db, actor, announcement_id):
    actor, row = await access(db, actor, announcement_id)
    return view(row, await receipt_for(db, actor, row), actor)


async def save(db, actor, payload, announcement_id=None):
    actor = await builtin_actor(db, actor)
    if announcement_id:
        row = await tenant_row(db, OAAnnouncement, actor, announcement_id)
        department = row.department_id
    else:
        department = payload.department_id
        announcement_id = str(uuid5(NAMESPACE_URL, actor.tenant_id + ':' + actor.user_id + ':announcement:' + payload.operation_id))
    target = OAAccessTarget(actor.tenant_id, None, department)
    async def perform(operation):
        if hasattr(payload, 'expected_revision'):
            row = await tenant_row(db, OAAnnouncement, actor, announcement_id, lock=True)
            if row.revision != payload.expected_revision:
                raise revision_conflict()
            if row.state != 'DRAFT':
                raise invalid('仅草稿可修改，已发布公告请撤回后新建')
            row.title, row.body, row.revision = payload.title, payload.body, row.revision + 1
        else:
            row = OAAnnouncement(id=announcement_id, tenant_id=actor.tenant_id,
                department_id=department, author_id=actor.user_id, title=payload.title, body=payload.body)
            db.add(row)
        await db.flush()
        await record_audit(db, actor=actor, resource='announcement', action='announcement.save',
            object_type='announcement', object_id=row.id, detail=dict(revision=row.revision))
        return CommandOutcome(result=view(row, None, actor))
    return await run_command(db, actor, OACommand(kind='announcement.save', target_id=announcement_id,
        target_version=str(getattr(payload, 'expected_revision', 0)), operation_id=payload.operation_id,
        payload=payload.model_dump(), resource='announcement', target=target), perform)


async def transition(db, actor, announcement_id, payload, action):
    actor = await builtin_actor(db, actor)
    row = await tenant_row(db, OAAnnouncement, actor, announcement_id)
    target = OAAccessTarget(actor.tenant_id, None, row.department_id)
    async def perform(operation):
        row = await tenant_row(db, OAAnnouncement, actor, announcement_id, lock=True)
        if row.revision != payload.expected_revision:
            raise revision_conflict()
        expected, state = ('DRAFT', 'PUBLISHED') if action == 'publish' else ('PUBLISHED', 'WITHDRAWN')
        if row.state != expected:
            raise invalid('当前公告状态不允许该操作')
        row.state, row.revision = state, row.revision + 1
        if action == 'publish':
            row.published_at = utcnow()
        else:
            row.withdrawn_at = utcnow()
        await record_audit(db, actor=actor, resource='announcement', action='announcement.' + action,
            object_type='announcement', object_id=row.id, detail=dict(revision=row.revision, state=state))
        return CommandOutcome(result=view(row, await receipt_for(db, actor, row), actor))
    return await run_command(db, actor, OACommand(kind='announcement.' + action, target_id=row.id,
        target_version=str(payload.expected_revision), operation_id=payload.operation_id,
        payload=payload.model_dump(), resource='announcement', target=target), perform)


async def mark_read(db, actor, announcement_id):
    actor = await builtin_actor(db, actor)
    await lock_tenant(db, actor.tenant_id)
    actor, row = await access(db, actor, announcement_id, lock=True)
    if row.state != 'PUBLISHED':
        raise invalid('只能确认已发布公告的阅读状态')
    receipt = await receipt_for(db, actor, row)
    if receipt is None:
        receipt = OAAnnouncementRead(tenant_id=actor.tenant_id, announcement_id=row.id,
            reader_id=actor.user_id, read_at=utcnow())
        db.add(receipt)
        await record_audit(db, actor=actor, resource='announcement', action='announcement.read',
            object_type='announcement', object_id=row.id, detail=dict(revision=row.revision))
    return view(row, receipt, actor)
