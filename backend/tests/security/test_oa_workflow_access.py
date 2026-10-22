import pytest
from app.core.errors import AppException
from app.models.identity import OAUser
from tests.oa_support import oa_db, seed


async def test_current_scope_and_no_admin_bypass(oa_db):
    from app.services.oa_access_service import authorize_oa, OAAccessTarget
    async with oa_db() as db:
        actor = await seed(db, resources=['workflow'])
        denied = await seed(db, tenant=actor.tenant_id)
        denied.roles.append('admin')
        await db.commit()
        target = OAAccessTarget(actor.tenant_id, department_id=actor.depts[0])
        assert (await authorize_oa(db, actor, 'workflow', 'write', target=target)).actor.user_id == actor.user_id
        with pytest.raises(AppException): await authorize_oa(db, denied, 'workflow', 'write', target=target)
        with pytest.raises(AppException):
            await authorize_oa(db, actor, 'workflow', 'write', target=OAAccessTarget('other', department_id=actor.depts[0]))
        with pytest.raises(AppException):
            await authorize_oa(db, actor, 'workflow', 'write', target=OAAccessTarget(actor.tenant_id, department_id=denied.depts[0]))
        row = await db.get(OAUser, actor.user_id)
        row.status = 'disabled'
        await db.flush()
        with pytest.raises(AppException): await authorize_oa(db, actor, 'workflow', 'write', target=target)


async def test_self_write_is_not_department_edit(oa_db):
    from app.services.oa_access_service import authorize_oa, OAAccessTarget
    async with oa_db() as db:
        actor = await seed(db, resources=['leave'])
        other = await seed(db, tenant=actor.tenant_id, department=actor.depts[0])
        await db.commit()
        target = OAAccessTarget(actor.tenant_id, owner_id=other.user_id, department_id=actor.depts[0])
        await authorize_oa(db, actor, 'leave', 'read', target=target)
        with pytest.raises(AppException): await authorize_oa(db, actor, 'leave', 'write', target=target)


def test_new_resources_are_assignable_not_automatic():
    from app.services.organization_service import BUSINESS_RESOURCES, RESOURCES
    for resource in ['leave','approval','workflow','leave_balance','workflow_admin']:
        assert resource in RESOURCES
        assert resource not in BUSINESS_RESOURCES
