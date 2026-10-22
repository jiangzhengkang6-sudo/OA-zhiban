"""Isolated manual OA fixtures; never use development model or identity state."""
import asyncio
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.db.migrations import migration_config
from app.db.session import AuthorizedSession
from app.models.identity import OAUser, OADepartment, OAMembership, OARole, OAPermission, OAUserRole, OARolePermission
from app.services.identity_service import current_identity
from tests.integration.test_identity_sessions import configured


@pytest.fixture
async def oa_db(safe_database, monkeypatch):
    from app.core import config
    from app.providers import identity
    monkeypatch.setattr(config, 'get_settings', configured)
    monkeypatch.setattr(identity, 'get_settings', configured)
    await asyncio.to_thread(command.upgrade, migration_config(), 'head')
    engine = create_async_engine(safe_database.database_url)
    yield async_sessionmaker(engine, class_=AuthorizedSession, expire_on_commit=False)
    await engine.dispose()


async def seed(db, *, tenant=None, department=None, resources=(), scope='department', manager=None):
    tenant = tenant or uuid4().hex
    if department is None:
        dept = OADepartment(tenant_id=tenant, name=uuid4().hex)
        db.add(dept)
        await db.flush()
        department = dept.id
    user = OAUser(tenant_id=tenant, normalized_username=uuid4().hex, display_name='测试成员', password_hash='unused')
    role = OARole(tenant_id=tenant, code='role_' + uuid4().hex, name='测试权限')
    db.add_all([user, role])
    await db.flush()
    db.add_all([OAMembership(tenant_id=tenant, user_id=user.id, department_id=department, manager_id=manager),
                OAUserRole(tenant_id=tenant, user_id=user.id, role_id=role.id)])
    for resource in resources:
        for action in ('read','write'):
            permission = await db.scalar(select(OAPermission).where(OAPermission.resource==resource,
                OAPermission.action==action, OAPermission.scope==scope))
            if permission is None:
                permission = OAPermission(resource=resource, action=action, scope=scope)
                db.add(permission)
                await db.flush()
            db.add(OARolePermission(tenant_id=tenant, role_id=role.id, permission_id=permission.id))
    await db.flush()
    return await current_identity(db, user)
