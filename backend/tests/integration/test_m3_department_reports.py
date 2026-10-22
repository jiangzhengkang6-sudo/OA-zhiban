"""Department aggregation intersects report scope with each live source grant."""
import pytest
from sqlalchemy import select

from app.core.errors import AppException
from app.models.identity import OAPermission, OARolePermission, OAUserRole
from app.models.work_task import WorkTask
from app.schemas.report import ReportInput, ReportPlanApproval
from app.services import report_query, report_service
from tests.api.test_oa_ticket import create
from tests.integration.test_m3_derived_authority import ended_reimbursement, move_member, reimbursement_task
from tests.integration.test_m3_document_sources import formal_documents
from tests.integration.test_m3_formal_sources import ended_leave, report_plan
from tests.m3_http_support import authenticated_client
from tests.oa_support import oa_db, seed


async def grant_scope(db, actor, resource, scope, action='read'):
    role_id = await db.scalar(select(OAUserRole.role_id).where(
        OAUserRole.tenant_id == actor.tenant_id, OAUserRole.user_id == actor.user_id))
    permission = await db.scalar(select(OAPermission).where(OAPermission.resource == resource,
        OAPermission.action == action, OAPermission.scope == scope))
    if permission is None:
        permission = OAPermission(resource=resource, action=action, scope=scope)
        db.add(permission)
        await db.flush()
    db.add(OARolePermission(tenant_id=actor.tenant_id, role_id=role_id, permission_id=permission.id))
    await db.commit()


def department_plan(metric):
    return report_plan(metric).model_copy(update={'scope': 'department'})


@pytest.mark.parametrize('source_scope', ['self', 'department'])
async def test_department_tickets_intersect_source_scope_and_current_membership(formal_documents, source_scope):
    async with formal_documents() as db:
        actor = await seed(db, resources=['report'])
        await grant_scope(db, actor, 'ticket', source_scope)
        await grant_scope(db, actor, 'ticket', 'self', action='write')
        peer = await seed(db, tenant=actor.tenant_id, department=actor.depts[0], resources=['ticket'], scope='self')
        outsider = await seed(db, tenant=actor.tenant_id, resources=['ticket'], scope='self')
        foreign = await seed(db, resources=['ticket'], scope='self')
        await db.commit()
        own, _, _ = await create(db, actor, key='own')
        shared, _, _ = await create(db, peer, key='peer')
        await create(db, outsider, key='other-department')
        await create(db, foreign, key='foreign-tenant')
        plan = department_plan('ticket_volume')
        snapshot = await report_query.execute_plan(actor, plan)
        expected = {own['id'], shared['id']} if source_scope == 'department' else {own['id']}
        assert set(snapshot['metrics'][0]['source_ids']) == expected
        assert snapshot['metrics'][0]['current'] == len(expected)
        assert (await report_query.execute_plan(actor, report_plan('ticket_volume')))['metrics'][0]['current'] == 1
        await report_query.validate_snapshot_scope(db, actor, plan, snapshot)


async def test_department_report_requires_department_report_permission(formal_documents):
    async with formal_documents() as db:
        actor = await seed(db, resources=['report', 'ticket'], scope='self')
        await db.commit()
        with pytest.raises(AppException) as denied:
            await report_query.execute_plan(actor, department_plan('ticket_volume'))
        assert denied.value.http_status == 403


@pytest.mark.parametrize('scene', ['leave', 'reimbursement'])
@pytest.mark.parametrize('source_scope', [None, 'self', 'department'])
async def test_department_approvals_use_scene_specific_source_permissions(formal_documents, monkeypatch, scene, source_scope):
    async with formal_documents() as db:
        if scene == 'leave':
            _, owner, _, instance = await ended_leave(db)
            instance_id = instance.id
        else:
            owner, _, instance = await ended_reimbursement(db, monkeypatch)
            instance_id = instance.id
        reader = await seed(db, tenant=owner.tenant_id, department=owner.depts[0], resources=['report'])
        await db.commit()
        if source_scope:
            await grant_scope(db, reader, scene, source_scope)
        plan = department_plan('approval_outcomes')
        if source_scope is None:
            with pytest.raises(AppException) as denied:
                await report_query.execute_plan(reader, plan)
            assert denied.value.http_status == 403
        else:
            snapshot = await report_query.execute_plan(reader, plan)
            expected = [instance_id] if source_scope == 'department' else []
            assert snapshot['metrics'][0]['source_ids'] == expected
            assert snapshot['metrics'][0]['current'] == len(expected)


@pytest.mark.parametrize('entry', ['detail', 'versions', 'approve_replay'])
async def test_department_report_cached_entries_reject_source_owner_move(formal_documents, entry):
    async with formal_documents() as db:
        actor = await seed(db, resources=['report', 'ticket'])
        peer = await seed(db, tenant=actor.tenant_id, department=actor.depts[0], resources=['ticket'], scope='self')
        await db.commit()
        ticket, _, _ = await create(db, peer)
        created = await report_service.create_report(db, actor, ReportInput(subject='部门工单统计',
            plan=department_plan('ticket_volume'), idempotency_key='department-report'))
        command = ReportPlanApproval(idempotency_key='department-approve', expected_version=1, plan_confirmed=True)
        generated = await report_service.approve_plan(db, actor, created.report_id, command)
        assert generated.status == 'DRAFT_READY' and generated.snapshot['metrics'][0]['current'] == 1
        assert 'source_ids' not in generated.snapshot['metrics'][0]
        await db.commit()
        await move_member(formal_documents, peer)
        with pytest.raises(AppException) as denied:
            if entry == 'detail':
                await report_service.get_report(db, actor, created.report_id)
            elif entry == 'versions':
                await report_service.list_versions(db, actor, created.report_id)
            else:
                await report_service.approve_plan(db, actor, created.report_id, command)
        assert denied.value.http_status == 403
        refreshed = await report_query.execute_plan(actor, department_plan('ticket_volume'))
        assert ticket['id'] not in refreshed['metrics'][0]['source_ids']


@pytest.mark.parametrize('assigned_to_reader', [False, True])
async def test_department_report_does_not_expand_work_task_participation(formal_documents, monkeypatch, assigned_to_reader):
    async with formal_documents() as db:
        owner, identifier, _ = await ended_reimbursement(db, monkeypatch)
        batch = await reimbursement_task(db, owner, identifier)
        reader = await seed(db, tenant=owner.tenant_id, department=owner.depts[0],
            resources=['report', 'work_task', 'reimbursement'])
        task = await db.scalar(select(WorkTask).where(WorkTask.task_id == batch.task_ids[0]))
        if assigned_to_reader:
            task.assignee_id = reader.user_id
        await db.commit()
        snapshot = await report_query.execute_plan(reader, department_plan('work_task_progress'))
        expected = [str(task.id)] if assigned_to_reader else []
        assert snapshot['metrics'][0]['source_ids'] == expected
        assert snapshot['metrics'][0]['current'] == len(expected)
        await report_query.validate_snapshot_scope(db, reader, department_plan('work_task_progress'), snapshot)


@pytest.mark.parametrize('source_scope', ['self', 'department'])
async def test_department_report_http_uses_builtin_login_and_live_source_membership(formal_documents, monkeypatch, source_scope):
    async with formal_documents() as db:
        actor = await seed(db, resources=['report'])
        await grant_scope(db, actor, 'ticket', source_scope)
        await grant_scope(db, actor, 'ticket', 'self', action='write')
        peer = await seed(db, tenant=actor.tenant_id, department=actor.depts[0], resources=['ticket'], scope='self')
        outsider = await seed(db, tenant=actor.tenant_id, resources=['ticket'], scope='self')
        await db.commit()
        await create(db, actor, key='http-own')
        await create(db, peer, key='http-peer')
        await create(db, outsider, key='http-outsider')
    async with authenticated_client(formal_documents, monkeypatch, actor) as client:
        response = await client.post('/api/reports', json={'subject': '部门工单统计',
            'plan': department_plan('ticket_volume').model_dump(mode='json'), 'idempotency_key': 'http-department'})
        assert response.status_code == 200, response.text
        report_id = response.json()['data']['report_id']
        approval = {'expected_version': 1, 'plan_confirmed': True, 'idempotency_key': 'http-department-approve'}
        generated = await client.post(f'/api/reports/{report_id}/approve-plan', json=approval)
        assert generated.status_code == 200, generated.text
        result = generated.json()['data']
        assert result['status'] == 'DRAFT_READY'
        assert result['snapshot']['metrics'][0]['current'] == (2 if source_scope == 'department' else 1)
        assert 'source_ids' not in result['snapshot']['metrics'][0]
        detail = await client.get(f'/api/reports/{report_id}')
        assert detail.status_code == 200, detail.text
        await move_member(formal_documents, peer)
        for path, body in [(f'/api/reports/{report_id}', None),
                (f'/api/reports/{report_id}/versions', None), (f'/api/reports/{report_id}/approve-plan', approval)]:
            response = await client.get(path) if body is None else await client.post(path, json=body)
            assert response.status_code == (403 if source_scope == 'department' else 200), response.text


async def test_department_report_http_rejects_self_only_report_permission(formal_documents, monkeypatch):
    async with formal_documents() as db:
        actor = await seed(db, resources=['report', 'ticket'], scope='self')
        await db.commit()
    async with authenticated_client(formal_documents, monkeypatch, actor) as client:
        response = await client.post('/api/reports', json={'subject': '无权部门统计',
            'plan': department_plan('ticket_volume').model_dump(mode='json'), 'idempotency_key': 'denied-department'})
        assert response.status_code == 403, response.text
        listing = await client.get('/api/reports')
        assert listing.status_code == 200, listing.text
        assert listing.json()['data']['items'] == []
