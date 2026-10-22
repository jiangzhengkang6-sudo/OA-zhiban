"""Formal audit scope uses current explicit permissions, never role names."""
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import select

from app.core.errors import AppException
from app.core.context import set_current_user
from app.models.identity import OARole, OAUserRole, OAMembership
from app.services import oa_scope_service, audit_export_service, document_service
from tests.m3_http_support import authenticated_client
from tests.integration.test_m3_document_sources import formal_documents as formal_audits
from tests.integration.test_m3_formal_sources import revoke
from tests.oa_support import oa_db, seed


async def fixture(db, *, scope='self', admin=False):
    actor = await seed(db, resources=['audit', 'document'], scope=scope)
    peer = await seed(db, tenant=actor.tenant_id, department=actor.depts[0])
    outside = await seed(db, tenant=actor.tenant_id)
    foreign = await seed(db)
    if admin:
        role = await db.scalar(select(OARole).join(OAUserRole, OARole.id == OAUserRole.role_id)
            .where(OAUserRole.user_id == actor.user_id))
        role.code = 'admin'
        actor.roles = ['admin']
    events = []
    for user in [actor, peer, outside, foreign]:
        events.append(await oa_scope_service.record_audit(db, actor=user, resource='document', action='generated'))
    await db.commit()
    return actor, peer, outside, events


async def test_formal_admin_role_cannot_expand_self_audit_scope(formal_audits):
    async with formal_audits() as db:
        actor, _, _, events = await fixture(db, admin=True)
        rows = await oa_scope_service.visible_audits(db, actor=actor)
        assert [row.id for row in rows] == [events[0].id]


async def test_formal_department_audit_scope_requires_explicit_permission(formal_audits):
    async with formal_audits() as db:
        actor, _, _, events = await fixture(db, scope='department')
        rows = await oa_scope_service.visible_audits(db, actor=actor)
        assert {row.id for row in rows} == {events[0].id, events[1].id}


async def test_formal_audit_permission_revocation_denies_cached_actor(formal_audits):
    async with formal_audits() as db:
        actor, _, _, _ = await fixture(db)
        await revoke(db, actor, 'audit')
        with pytest.raises(AppException) as denied:
            await oa_scope_service.visible_audits(db, actor=actor)
        assert denied.value.http_status == 403


async def test_formal_audit_department_move_uses_current_membership(formal_audits):
    async with formal_audits() as db:
        actor, _, outside, events = await fixture(db, scope='department')
        member = await db.scalar(select(OAMembership).where(OAMembership.user_id == actor.user_id))
        member.department_id = outside.depts[0]
        await db.commit()
        rows = await oa_scope_service.visible_audits(db, actor=actor)
        assert {row.id for row in rows} == {events[0].id, events[2].id}


async def test_formal_audit_hides_document_after_source_revocation(formal_audits):
    from tests.integration.test_m3_document_sources import setup, payload
    async with formal_audits() as db:
        actor, _, binding = await setup(db)
        binding.access_scope = 'department'
        # Give the document author explicit audit access without granting knowledge to an auditor.
        audit_actor = await seed(db, tenant=actor.tenant_id, department=actor.depts[0],
            resources=['audit', 'document', 'knowledge'], scope='department')
        created = await document_service.create_document(db, actor, payload())
        await db.commit()
        assert any(row.object_id == created.document_id for row in await oa_scope_service.visible_audits(db, actor=audit_actor))
        binding.status = 'revoked'
        await db.commit()
        assert not any(row.object_id == created.document_id for row in await oa_scope_service.visible_audits(db, actor=audit_actor))


async def test_formal_audit_business_permission_is_required(formal_audits):
    async with formal_audits() as db:
        actor, _, _, _ = await fixture(db)
        await revoke(db, actor, 'document')
        assert await oa_scope_service.visible_audits(db, actor=actor) == []


async def test_formal_export_filters_and_serializes_datetime(formal_audits):
    async with formal_audits() as db:
        actor, _, _, events = await fixture(db, scope='department')
        set_current_user(actor)
        filters = {'action': 'generated', 'actor_id': actor.user_id,
            'start_time': datetime.now(timezone.utc) - timedelta(minutes=5), 'page_size': 1}
        export = await audit_export_service.create_export(db, requested_by=actor.user_id,
            meeting_tenant_id=actor.tenant_id, filters=filters)
        await db.commit()
        payload = json.loads(audit_export_service.download_path(export).read_bytes())
        assert [row['id'] for row in payload['items']] == [events[0].id]
        assert export.row_count == 1


@pytest.mark.parametrize('entry', ['detail', 'download'])
@pytest.mark.parametrize('change', ['owner', 'scope', 'permission', 'expiry'])
async def test_formal_export_http_rechecks_authority(formal_audits, monkeypatch, entry, change):
    async with formal_audits() as db:
        actor, peer, _, _ = await fixture(db, scope='department')
        set_current_user(actor)
        export = await audit_export_service.create_export(db, requested_by=actor.user_id,
            meeting_tenant_id=actor.tenant_id, filters={})
        await db.commit()
        if change == 'owner':
            # Same tenant and department, but a different export creator.
            role = await db.scalar(select(OARole).join(OAUserRole, OARole.id == OAUserRole.role_id)
                .where(OAUserRole.user_id == peer.user_id))
            # Reuse the explicit audit role so a denial cannot be attributed to missing permission.
            own_role = await db.scalar(select(OAUserRole).where(OAUserRole.user_id == actor.user_id))
            db.add(OAUserRole(tenant_id=actor.tenant_id, user_id=peer.user_id, role_id=own_role.role_id))
            role.code = 'admin'
            request_actor = peer
        else:
            role = await db.scalar(select(OARole).join(OAUserRole, OARole.id == OAUserRole.role_id)
                .where(OAUserRole.user_id == actor.user_id))
            role.code = 'admin'
            request_actor = actor
            if change == 'scope':
                from app.models.identity import OAPermission, OARolePermission
                permission_ids = select(OAPermission.id).where(OAPermission.resource == 'audit', OAPermission.scope == 'department')
                from sqlalchemy import delete
                await db.execute(delete(OARolePermission).where(OARolePermission.role_id == role.id,
                    OARolePermission.permission_id.in_(permission_ids)))
                permission = await db.scalar(select(OAPermission).where(OAPermission.resource == 'audit',
                    OAPermission.action == 'read', OAPermission.scope == 'self'))
                if permission is None:
                    permission = OAPermission(resource='audit', action='read', scope='self')
                    db.add(permission)
                    await db.flush()
                db.add(OARolePermission(tenant_id=actor.tenant_id, role_id=role.id, permission_id=permission.id))
            elif change == 'permission':
                await revoke(db, actor, 'document')
            else:
                export.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
    async with authenticated_client(formal_audits, monkeypatch, request_actor) as client:
        url = f'/api/audit/exports/{export.id}' + ('/download' if entry == 'download' else '')
        response = await client.get(url)
        assert response.status_code in {403, 410}, response.text


async def test_formal_audit_http_uses_permissions_and_honors_filters(formal_audits, monkeypatch):
    async with formal_audits() as db:
        actor, _, _, events = await fixture(db, scope='department')
    async with authenticated_client(formal_audits, monkeypatch, actor) as client:
        listed = await client.get('/api/audit/events', params={'actor_id': actor.user_id})
        assert listed.status_code == 200, listed.text
        assert [row['id'] for row in listed.json()['data']['items']] == [events[0].id]
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        empty = await client.get('/api/audit/events', params={'start_time': future})
        assert empty.status_code == 200 and empty.json()['data']['total'] == 0, empty.text
        created = await client.post('/api/audit/exports', json={'actor_id': actor.user_id})
        assert created.status_code == 200, created.text
        export = created.json()['data']
        downloaded = await client.get(export['download_url'])
        assert downloaded.status_code == 200, downloaded.text
        assert [row['id'] for row in downloaded.json()['items']] == [events[0].id]


@pytest.mark.parametrize('entry', ['detail', 'download'])
@pytest.mark.parametrize('change', ['binding', 'tamper', 'department'])
async def test_formal_export_http_rechecks_sources_and_file(formal_audits, monkeypatch, entry, change):
    from app.models.oa_ai_scope import OAKnowledgeBinding
    from tests.integration.test_m3_document_sources import setup, payload
    async with formal_audits() as db:
        actor, _, binding = await setup(db)
        binding.access_scope = 'department'
        auditor = await seed(db, tenant=actor.tenant_id, department=actor.depts[0],
            resources=['audit', 'document', 'knowledge'], scope='department')
        outside = await seed(db, tenant=actor.tenant_id)
        await document_service.create_document(db, actor, payload())
        await db.commit()
        set_current_user(auditor)
        export = await audit_export_service.create_export(db, requested_by=auditor.user_id,
            meeting_tenant_id=auditor.tenant_id, filters={})
        await db.commit()
        assert export.row_count > 0
    async with authenticated_client(formal_audits, monkeypatch, auditor) as client:
        url = f'/api/audit/exports/{export.id}' + ('/download' if entry == 'download' else '')
        before = await client.get(url)
        assert before.status_code == 200, before.text
        if change == 'tamper':
            path = audit_export_service.download_path(export)
            path.write_bytes(path.read_bytes() + b' ')
        else:
            async with formal_audits() as db:
                if change == 'binding':
                    current = await db.get(OAKnowledgeBinding, binding.id)
                    current.status = 'revoked'
                else:
                    member = await db.scalar(select(OAMembership).where(OAMembership.user_id == auditor.user_id))
                    member.department_id = outside.depts[0]
                await db.commit()
        denied = await client.get(url)
        assert denied.status_code == 403, denied.text


async def test_formal_audit_http_thread_filter_matches_export(formal_audits, monkeypatch):
    from uuid import uuid4
    async with formal_audits() as db:
        actor, _, _, events = await fixture(db)
        thread_id = str(uuid4())
        events[0].detail = {'thread_id': thread_id}
        await db.commit()
    async with authenticated_client(formal_audits, monkeypatch, actor) as client:
        listed = await client.get('/api/audit/events', params={'thread_id': thread_id})
        assert listed.status_code == 200, listed.text
        assert [row['id'] for row in listed.json()['data']['items']] == [events[0].id]
        created = await client.post('/api/audit/exports', json={'thread_id': thread_id})
        assert created.status_code == 200, created.text
        public = created.json()['data']
        assert '_formal_audit' not in public['filters']
        downloaded = await client.get(public['download_url'])
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.json()['filters']['thread_id'] == thread_id
        assert [row['id'] for row in downloaded.json()['items']] == [events[0].id]
