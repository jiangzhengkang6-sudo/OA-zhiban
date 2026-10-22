"""Formal contract participants use live permissions, never privileged role names."""
import pytest

from app.core.errors import AppException
from app.models.identity import OAUser, OARole, OAUserRole
from app.models.contract_record import ContractRecord
from app.models.contract_review_version import ContractReviewVersion
from app.schemas.contract import ContractInput, ContractCommand
from app.services import contract_service as contracts
from tests.integration.test_m3_formal_sources import revoke
from tests.oa_support import oa_db, seed


async def participants(db):
    owner = await seed(db, resources=['contract'])
    reviewer = await seed(db, tenant=owner.tenant_id, resources=['contract'])
    await db.commit()
    return owner, reviewer


async def create(db, owner, reviewer, key='formal-contract'):
    return await contracts.create_contract(db, owner, ContractInput(title='采购合同',
        text='付款条款：三十日内付款。', reviewer_id=reviewer.user_id, idempotency_key=key))


async def ready(db, owner, reviewer):
    result = await create(db, owner, reviewer)
    from sqlalchemy import select
    row = await db.scalar(select(ContractRecord).where(ContractRecord.contract_id == result['contract_id']))
    row.status, row.current_version = 'DRAFT_READY', 1
    db.add(ContractReviewVersion(contract_id=row.id, version=1, draft={'risks': [], 'summary': '待人工复核'}))
    await db.commit()
    return result['contract_id']


async def test_formal_designated_reviewer_without_legacy_roles_can_read_and_decide(oa_db):
    async with oa_db() as db:
        owner, reviewer = await participants(db)
        assert not set(reviewer.roles).intersection({'approver', 'admin'})
        identifier = await ready(db, owner, reviewer)
        detail = await contracts.get_contract(db, reviewer, identifier)
        assert detail['available_actions'] == ['confirm', 'reject']
        assert (await contracts.list_contracts(db, reviewer))['total'] == 1
        result = await contracts.command_contract(db, reviewer, identifier, ContractCommand(
            action='confirm', expected_version=1, idempotency_key='formal-decision', comment='人工复核通过'))
        await db.commit()
        assert result['status'] == 'CONFIRMED'
        await revoke(db, reviewer, 'contract')
        with pytest.raises(AppException) as denied:
            await contracts.command_contract(db, reviewer, identifier, ContractCommand(
                action='confirm', expected_version=1, idempotency_key='formal-decision', comment='人工复核通过'))
        assert denied.value.http_status == 403


async def test_formal_read_only_reviewer_has_no_mutating_actions(oa_db):
    async with oa_db() as db:
        owner, reviewer = await participants(db)
        identifier = await ready(db, owner, reviewer)
        from sqlalchemy import delete, select
        from app.models.identity import OAPermission, OARolePermission
        await db.execute(delete(OARolePermission).where(OARolePermission.role_id.in_(
            select(OAUserRole.role_id).where(OAUserRole.user_id == reviewer.user_id)),
            OARolePermission.permission_id.in_(select(OAPermission.id).where(
                OAPermission.resource == 'contract', OAPermission.action == 'write'))))
        await db.commit()
        assert (await contracts.get_contract(db, reviewer, identifier))['available_actions'] == []
        with pytest.raises(AppException) as denied:
            await contracts.command_contract(db, reviewer, identifier, ContractCommand(
                action='confirm', expected_version=1, idempotency_key='read-only', comment='越权'))
        assert denied.value.http_status == 403


async def test_formal_admin_role_without_contract_permission_cannot_be_designated(oa_db):
    async with oa_db() as db:
        owner, _ = await participants(db)
        reviewer = await seed(db, tenant=owner.tenant_id)
        role = OARole(tenant_id=owner.tenant_id, code='admin', name='角色名不授予合同权限')
        db.add(role)
        await db.flush()
        db.add(OAUserRole(tenant_id=owner.tenant_id, role_id=role.id, user_id=reviewer.user_id))
        await db.commit()
        with pytest.raises(AppException) as denied:
            await create(db, owner, reviewer)
        assert denied.value.http_status == 403


async def test_formal_disabled_reviewer_is_authorization_error_not_dependency_failure(oa_db):
    async with oa_db() as db:
        owner, reviewer = await participants(db)
        user = await db.get(OAUser, reviewer.user_id)
        user.status = 'disabled'
        await db.commit()
        with pytest.raises(AppException) as denied:
            await create(db, owner, reviewer)
        assert denied.value.http_status == 401


async def test_formal_contract_is_private_even_for_department_reader(oa_db):
    async with oa_db() as db:
        owner, reviewer = await participants(db)
        identifier = await ready(db, owner, reviewer)
        outsider = await seed(db, tenant=owner.tenant_id, department=owner.depts[0], resources=['contract'])
        other_tenant = await seed(db, resources=['contract'])
        await db.commit()
        for reader in (outsider, other_tenant):
            with pytest.raises(AppException) as denied:
                await contracts.get_contract(db, reader, identifier)
            assert denied.value.http_status == 404
