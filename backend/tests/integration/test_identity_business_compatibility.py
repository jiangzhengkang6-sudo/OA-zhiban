"""Real identity/resource compatibility on an isolated database, without model calls."""
import pytest
from app.core.errors import AppException
from app.models.identity import OAUser
from app.schemas.organization import DepartmentInput, RoleInput, UserCreate, UserUpdate
from app.services import identity_service as identities, organization_service as org
from tests.integration.test_identity_sessions import identity_db, new_admin
from tests.integration.test_identity_authorization import builtin


async def test_custom_role_business_identity_and_tool_boundary(identity_db, builtin):
    from app.services import document_service, email_service, meeting_service
    from app.services import report_service, contract_service, work_task_service
    tenant, uid = await new_admin(identity_db)
    resources = ('document', 'email', 'meeting', 'report', 'contract', 'work_task')
    async with identity_db() as db:
        admin = await identities.current_identity(db, await db.get(OAUser, uid))
        role = await org.save_role(db, admin, RoleInput(code='specialist', name='专员', permissions=[
            dict(resource=r, action='read', scope='self') for r in resources]))
        user = await org.create_user(db, admin, UserCreate(username='specialist', display_name='专员',
            password='Test-password-123!', role_ids=[role['id']]))
        actor = await identities.current_identity(db, await db.get(OAUser, user['id']))
        for service in (document_service, email_service, meeting_service, report_service, contract_service, work_task_service):
            assert (await service._identity(db, actor)).roles == ['specialist']
        assert (await document_service.list_documents(db, actor)).total == 0
        with pytest.raises(AppException) as denied:
            await work_task_service.save_draft(db, actor, 'missing', None)
        assert denied.value.http_status == 403


def test_write_permission_requires_corresponding_read_scope():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RoleInput(code='writer', name='编辑', permissions=[dict(resource='document',action='write',scope='self')])
    with pytest.raises(ValidationError):
        RoleInput(code='writer', name='编辑', permissions=[dict(resource='document',action='read',scope='self'),
            dict(resource='document',action='write',scope='department')])
    RoleInput(code='writer', name='编辑', permissions=[dict(resource='document',action='read',scope='department'),
        dict(resource='document',action='write',scope='self')])


async def test_department_lists_detail_versions_and_transfer(identity_db, builtin):
    from uuid import uuid4
    from app.core.context import CurrentUser
    from app.models.agent_thread import AgentThread
    from app.models.document_record import DocumentRecord
    from app.services import document_service as documents, task_service
    tenant, uid = await new_admin(identity_db)
    async with identity_db() as db:
        admin = await identities.current_identity(db, await db.get(OAUser, uid))
        dep_a = await org.save_department(db, admin, DepartmentInput(name='甲部门'))
        dep_b = await org.save_department(db, admin, DepartmentInput(name='乙部门'))
        role = await org.save_role(db, admin, RoleInput(code='department_reader', name='部门查看', permissions=[
            dict(resource='document', action='read', scope='department')]))
        users = []
        for name, dep in [('reader',dep_a),('colleague',dep_a),('other',dep_b)]:
            users.append(await org.create_user(db, admin, UserCreate(username=name, display_name=name,
                password='Test-password-123!', department_id=dep['id'], role_ids=[role['id']])))
        for user in users:
            thread = AgentThread(user_id=user['id'], tenant_id=tenant, scene='document',business_id=user['id'])
            db.add(thread)
            await db.flush()
            db.add(DocumentRecord(document_id=user['id'],thread_id=thread.id,tenant_id=tenant,owner_id=user['id'],
                template_id='notice',template_version=1,subject='材料',recipient='成员',distribution='内部',idempotency_key=uuid4().hex))
        await db.commit()
        actor = await identities.current_identity(db, await db.get(OAUser, users[0]['id']))
        assert {r.document_id for r in (await documents.list_documents(db,actor)).items} == {u['id'] for u in users[:2]}
        assert (await documents.get_document(db,actor,users[1]['id'])).document_id == users[1]['id']
        assert await documents.list_versions(db,actor,users[1]['id']) == []
        with pytest.raises(AppException) as denied:
            await documents.get_document(db,actor,users[2]['id'])
        assert denied.value.http_status == 404
        # Organization authority never implies sensitive business access.
        with pytest.raises(AppException) as denied:
            await documents.get_document(db,admin,users[0]['id'])
        assert denied.value.http_status == 403
        assert (await task_service.list_tasks(db,actor)).total == 1
        await org.update_user(db,admin,users[0]['id'],UserUpdate(display_name='reader',department_id=dep_b['id'],role_ids=[role['id']]))
        with pytest.raises(AppException) as stale:
            await documents.list_documents(db,actor)
        assert stale.value.http_status == 403
    async with identity_db() as db:
        actor = CurrentUser(users[0]['id'],tenant)
        assert {r.document_id for r in (await documents.list_documents(db,actor)).items} == {users[0]['id'],users[2]['id']}
        with pytest.raises(AppException):
            await documents.list_versions(db,actor,users[1]['id'])


async def test_builtin_tools_require_permission_and_disabled_background_actor(identity_db, builtin, monkeypatch):
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from uuid import uuid4
    from app.core.context import CurrentUser
    from app.services.authorization_service import authorize_tool
    from app.services.work_task_scheduler import _notify_task
    from app.services import work_task_service
    tenant, uid = await new_admin(identity_db)
    async with identity_db() as db:
        admin = await identities.current_identity(db, await db.get(OAUser, uid))
        with pytest.raises(AppException) as blocked:
            await authorize_tool(admin,'leave','get_leave_balance',session=db)
        assert blocked.value.http_status == 403
        user = await org.create_user(db,admin,UserCreate(username='disabled',display_name='停用成员',password='Test-password-123!'))
        await org.update_user(db,admin,user['id'],UserUpdate(display_name='停用成员',status='disabled',role_ids=user['role_ids']))
        async def forbidden_source(*args):
            pytest.fail('停用身份不得继续加载后台来源')
        monkeypatch.setattr(work_task_service,'_source_access',forbidden_source)
        task = SimpleNamespace(batch_id=uuid4(),tenant_id=tenant,assignee_id=user['id'],creator_id=user['id'],due_at=datetime.now(timezone.utc))
        assert await _notify_task(db,task,datetime.now(timezone.utc)) == 0


@pytest.mark.parametrize(('path', 'status'), [('/api/knowledge',403),
    ('/api/admin/agent-policies',403),('/api/audit/events',403),
    ('/api/audit/exports/legacy/download',403),('/api/operations/metrics',503)])
async def test_builtin_unscoped_admin_routes_fail_closed(identity_db, builtin, path, status, monkeypatch):
    from starlette.requests import Request
    from app.api import deps
    tenant, uid = await new_admin(identity_db)
    async with identity_db() as db:
        admin = await identities.current_identity(db,await db.get(OAUser,uid))
        monkeypatch.setattr(deps,'_ctx_user',lambda:admin)
        with pytest.raises(AppException) as denied:
            await deps.get_current_user(Request({'type':'http','path':path,'method':'GET','headers':[]}),db)
        assert denied.value.http_status == status


async def test_builtin_source_tools_require_source_permissions(identity_db, builtin):
    from types import SimpleNamespace
    from app.tools.work_task_tools import read_work_task_source
    from app.services.report_query import source_query, validate_snapshot_scope
    tenant, uid = await new_admin(identity_db)
    async with identity_db() as db:
        admin = await identities.current_identity(db,await db.get(OAUser,uid))
        role = await org.save_role(db,admin,RoleInput(code='task_reader',name='任务查看',permissions=[
            dict(resource='work_task',action='read',scope='self')]))
        user = await org.create_user(db,admin,UserCreate(username='task_reader',display_name='成员',
            password='Test-password-123!',role_ids=[role['id']]))
        actor = await identities.current_identity(db,await db.get(OAUser,user['id']))
        with pytest.raises(AppException) as denied:
            await read_work_task_source(db,actor,'meeting','missing')
        assert denied.value.message == '当前账号没有该操作权限'
        for source in ('ticket','approval'):
            with pytest.raises(AppException) as denied:
                await read_work_task_source(db,actor,source,'missing')
            assert denied.value.http_status == 403
        for metric in ('ticket_volume','approval_outcomes'):
            with pytest.raises(AppException) as denied:
                source_query(metric,actor,'own')
            assert denied.value.http_status == 403
        actor.data_scope['permissions'] = [dict(resource='report',action='read',scope='self')]
        with pytest.raises(AppException) as denied:
            source_query('work_task_progress',actor,'own')
        assert denied.value.http_status == 403
        with pytest.raises(AppException) as denied:
            await validate_snapshot_scope(db,actor,SimpleNamespace(scope='own'),{
                'metrics':[{'metric_id':'work_task_progress','source_ids':[]}]})
        assert denied.value.http_status == 403
