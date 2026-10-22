import pytest
from uuid import uuid4
from sqlalchemy import select
from app.core.context import CurrentUser
from app.core.errors import AppException
from app.models.identity import OAUser, OARole
from app.services import identity_service as identities
from tests.integration.test_identity_sessions import identity_db, new_admin, configured
from tests.integration.test_identity_authorization import builtin


async def test_organization_lifecycle_cycles_and_last_admin(identity_db, builtin):
    from app.services import organization_service as org
    from app.schemas.organization import DepartmentInput, UserCreate, UserUpdate
    tenant, uid = await new_admin(identity_db)
    async with identity_db() as db:
        actor = await identities.current_identity(db, await db.get(OAUser, uid))
        department = await org.save_department(db, actor, DepartmentInput(name='研发'))
        child = await org.save_department(db, actor, DepartmentInput(name='应用', parent_id=department['id']))
        with pytest.raises(AppException):
            await org.save_department(db, actor, DepartmentInput(name='研发', parent_id=child['id']), department['id'])
        await db.rollback()
        with pytest.raises(AppException):
            await org.update_user(db, actor, uid, UserUpdate(display_name='管理员', status='disabled', role_ids=[]))
        await db.rollback()
        employee = await org.create_user(db, actor, UserCreate(username='employee', display_name='员工', password='Test-password-123!', department_id=department['id']))
        with pytest.raises(AppException):
            await org.save_department(db, actor, DepartmentInput(name='研发', enabled=False), department['id'])
        await db.rollback()
        await org.update_user(db, actor, employee['id'], UserUpdate(display_name='员工', status='disabled', department_id=department['id'], role_ids=employee['role_ids']))
        assert (await db.get(OAUser, employee['id'], populate_existing=True)).handoff_pending


async def test_employee_management_denied_and_audit_rollback(identity_db, builtin, monkeypatch):
    from app.services import organization_service as org
    from app.schemas.organization import UserCreate, UserUpdate
    tenant, uid = await new_admin(identity_db)
    async with identity_db() as db:
        actor = await identities.current_identity(db, await db.get(OAUser, uid))
        employee = await org.create_user(db, actor, UserCreate(username='emp', display_name='员工', password='Test-password-123!'))
        other = await identities.current_identity(db, await db.get(OAUser, employee['id']))
        with pytest.raises(AppException):
            await org.overview(db, other)
        await db.rollback()
        def fail(*args, **kwargs):
            raise RuntimeError('audit unavailable')
        monkeypatch.setattr(org, 'audit', fail)
        with pytest.raises(RuntimeError):
            await org.update_user(db, actor, employee['id'], UserUpdate(display_name='员工', status='disabled', role_ids=employee['role_ids']))
        await db.rollback()
        assert (await db.get(OAUser, employee['id'], populate_existing=True)).status == 'active'


async def test_lifecycle_revokes_sessions_and_enable_does_not_restore(identity_db, builtin):
    from app.services import organization_service as org
    from app.schemas.organization import UserCreate, UserUpdate, ResetPassword
    tenant, uid = await new_admin(identity_db)
    async with identity_db() as db:
        admin = await identities.current_identity(db, await db.get(OAUser, uid))
        emp = await org.create_user(db, admin, UserCreate(username='emp', display_name='员工', password='Test-password-123!'))
        first = await identities.login(db, 'emp', 'Test-password-123!', source=uuid4().hex, tenant_id=tenant, settings=configured())
        await org.update_user(db, admin, emp['id'], UserUpdate(display_name='员工',status='disabled',role_ids=emp['role_ids']))
        await org.update_user(db, admin, emp['id'], UserUpdate(display_name='员工',status='active',role_ids=emp['role_ids']))
        with pytest.raises(AppException):
            await identities.resolve_access(first.grant.access_token,session=db,settings=configured())
        await db.rollback()
        with pytest.raises(AppException):
            await identities.rotate_refresh(first.refresh,session=db,settings=configured())
        await db.rollback()
        second = await identities.login(db, 'emp', 'Test-password-123!', source=uuid4().hex, tenant_id=tenant, settings=configured())
        await org.reset_password(db,admin,emp['id'],ResetPassword(password='New-password-123!'))
        with pytest.raises(AppException):
            await identities.resolve_access(second.grant.access_token,session=db,settings=configured())
        await db.rollback()
        grant = await identities.login(db,'emp','New-password-123!',source=uuid4().hex,tenant_id=tenant,settings=configured())
        assert grant.grant.user.user_id == emp['id']


async def test_role_and_department_changes_invalidate_old_snapshot(identity_db, builtin):
    from app.services import organization_service as org
    from app.services.authorization_service import require_fresh_identity, require_permission
    from app.schemas.organization import UserCreate, UserUpdate, DepartmentInput, RoleInput
    tenant, uid = await new_admin(identity_db)
    async with identity_db() as db:
        admin = await identities.current_identity(db,await db.get(OAUser,uid))
        a = await org.save_department(db,admin,DepartmentInput(name='甲'))
        b = await org.save_department(db,admin,DepartmentInput(name='乙'))
        emp = await org.create_user(db,admin,UserCreate(username='emp',display_name='员工',password='Test-password-123!',department_id=a['id']))
        old = await identities.current_identity(db,await db.get(OAUser,emp['id']))
        await org.update_user(db,admin,emp['id'],UserUpdate(display_name='员工',department_id=b['id'],role_ids=emp['role_ids']))
        with pytest.raises(AppException):
            await require_fresh_identity(old,session=db)
        await db.rollback()
        fresh = await identities.current_identity(db,await db.get(OAUser,emp['id'],populate_existing=True))
        assert fresh.depts == [b['id']]
        await org.save_role(db,admin,RoleInput(code='employee',name='员工',permissions=[]),emp['role_ids'][0])
        with pytest.raises(AppException):
            await require_fresh_identity(fresh,session=db)
        await db.rollback()
        current = await identities.current_identity(db,await db.get(OAUser,emp['id'],populate_existing=True))
        with pytest.raises(AppException):
            require_permission(current,'meeting','read')


async def test_concurrent_last_admin_and_cross_tenant_rejected(identity_db, builtin):
    import asyncio
    from app.services import organization_service as org
    from app.schemas.organization import UserCreate, UserUpdate, DepartmentInput
    tenant, uid = await new_admin(identity_db)
    async with identity_db() as db:
        admin = await identities.current_identity(db,await db.get(OAUser,uid))
        role = await db.scalar(select(OARole).where(OARole.tenant_id==tenant,OARole.code=='admin'))
        second = await org.create_user(db,admin,UserCreate(username='admin2',display_name='二号',password='Test-password-123!',role_ids=[role.id]))
    async def disable(user_id):
        async with identity_db() as db:
            actor = await identities.current_identity(db,await db.get(OAUser,user_id))
            try:
                await org.update_user(db,actor,user_id,UserUpdate(display_name='停用',status='disabled',role_ids=[]))
                return True
            except AppException:
                await db.rollback()
                return False
    assert sum(await asyncio.gather(disable(uid),disable(second['id'])))==1
    other_tenant, other_uid = await new_admin(identity_db)
    async with identity_db() as db:
        actor = await identities.current_identity(db,await db.get(OAUser,other_uid))
        with pytest.raises(AppException):
            await org.update_user(db,actor,uid,UserUpdate(display_name='越界',role_ids=[]))
