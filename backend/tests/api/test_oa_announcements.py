from uuid import uuid4

import pytest
from sqlalchemy import func, select, delete
from app.core.errors import AppException
from app.models.identity import OAMembership, OARolePermission, OAUser
from app.models.oa_announcement import OAAnnouncement, OAAnnouncementRead
from app.models.oa_ai_scope import OABusinessAudit
from app.schemas.oa_announcement import AnnouncementCreate, AnnouncementUpdate
from app.schemas.oa_leave import OACommand
from app.services import oa_announcement_service as service
from tests.oa_support import oa_db, seed


def command(revision):
    return OACommand(operation_id=str(uuid4()), expected_revision=revision)


async def draft(db, actor):
    payload = AnnouncementCreate(operation_id=str(uuid4()), department_id=actor.depts[0],
        title='设备维护通知', body='周五 18:00 开始维护，请提前保存工作。')
    result = await service.save(db, actor, payload)
    await db.commit()
    return result.result, payload


async def test_publication_read_and_withdraw_are_versioned_and_idempotent(oa_db):
    async with oa_db() as db:
        author = await seed(db, resources=['announcement'])
        reader = await seed(db, tenant=author.tenant_id, department=author.depts[0], resources=['announcement'], scope='self')
        row, payload = await draft(db, author)
        assert (await service.save(db, author, payload)).replayed
        assert await service.list_items(db, reader) == []
        with pytest.raises(AppException): await service.detail(db, reader, row['id'])
        publish = command(1)
        result = await service.transition(db, author, row['id'], publish, 'publish')
        await db.commit()
        assert result.result['state'] == 'PUBLISHED'
        assert (await service.transition(db, author, row['id'], publish, 'publish')).replayed
        assert len(await service.list_items(db, reader)) == 1
        assert (await service.detail(db, reader, row['id']))['read_at'] is None
        first = await service.mark_read(db, reader, row['id'])
        await db.commit()
        second = await service.mark_read(db, reader, row['id'])
        await db.commit()
        assert first['read_at'] == second['read_at']
        assert await db.scalar(select(func.count()).select_from(OAAnnouncementRead).where(OAAnnouncementRead.tenant_id==author.tenant_id)) == 1
        assert await db.scalar(select(func.count()).select_from(OABusinessAudit).where(OABusinessAudit.tenant_id==author.tenant_id, OABusinessAudit.action=='announcement.read')) == 1
        with pytest.raises(AppException):
            await service.save(db, author, AnnouncementUpdate(operation_id=str(uuid4()), expected_revision=2,
                title='禁止改写已发布正文', body='新内容'), row['id'])
        await service.transition(db, author, row['id'], command(2), 'withdraw')
        await db.commit()
        assert await service.list_items(db, reader) == []
        with pytest.raises(AppException) as error: await service.detail(db, reader, row['id'])
        assert error.value.http_status == 404
        assert (await service.list_items(db, author, manage=True))[0]['state'] == 'WITHDRAWN'


@pytest.mark.parametrize('boundary', ['tenant', 'department', 'read_only', 'revoked', 'disabled', 'transfer'])
async def test_current_authority_and_department_boundaries(oa_db, boundary):
    async with oa_db() as db:
        author = await seed(db, resources=['announcement'])
        row, _ = await draft(db, author)
        await service.transition(db, author, row['id'], command(1), 'publish')
        await db.commit()
        if boundary == 'tenant':
            actor = await seed(db, resources=['announcement'])
        elif boundary == 'department':
            actor = await seed(db, tenant=author.tenant_id, resources=['announcement'])
        else:
            actor = await seed(db, tenant=author.tenant_id, department=author.depts[0], resources=['announcement'], scope='self')
        await db.commit()
        if boundary == 'read_only':
            with pytest.raises(AppException) as error:
                await service.transition(db, actor, row['id'], command(2), 'withdraw')
            assert error.value.http_status == 403
            return
        if boundary == 'revoked':
            from app.models.identity import OAUserRole
            roles = select(OAUserRole.role_id).where(OAUserRole.user_id == actor.user_id)
            await db.execute(delete(OARolePermission).where(OARolePermission.tenant_id==actor.tenant_id, OARolePermission.role_id.in_(roles)))
        elif boundary == 'disabled':
            (await db.get(OAUser, actor.user_id)).status = 'disabled'
        elif boundary == 'transfer':
            other = await seed(db, tenant=author.tenant_id)
            (await db.get(OAMembership, (actor.tenant_id, actor.user_id))).department_id = other.depts[0]
        await db.commit()
        for operation in (service.detail, service.mark_read):
            with pytest.raises(AppException): await operation(db, actor, row['id'])


async def test_stale_versions_payload_conflicts_and_draft_edits(oa_db):
    async with oa_db() as db:
        actor = await seed(db, resources=['announcement'])
        row, payload = await draft(db, actor)
        payload.body = '相同操作号对应另一正文'
        with pytest.raises(AppException) as error: await service.save(db, actor, payload)
        assert error.value.http_status == 409
        updated = await service.save(db, actor, AnnouncementUpdate(operation_id=str(uuid4()),
            expected_revision=1, title='维护通知更新', body='维护延迟至 19:00'), row['id'])
        await db.commit()
        assert updated.result['revision'] == 2
        with pytest.raises(AppException) as error: await service.transition(db, actor, row['id'], command(1), 'publish')
        assert error.value.http_status == 409
        assert (await db.get(OAAnnouncement, row['id'])).state == 'DRAFT'
