"""People selectors and writes share live, tenant-scoped management authority."""
import pytest
from app.core.errors import AppException
from app.models.identity import OAUser
from app.schemas.oa_leave import BalanceAdjustment
from app.schemas.oa_workflow import WorkflowSave
from app.services import oa_workflow_service as workflows, oa_balance_service as balances
from app.services import contract_service as contracts
from tests.oa_support import oa_db, seed
from tests.unit.test_oa_workflow_definition import definition


async def test_organization_manager_sees_and_adjusts_other_departments(oa_db):
    async with oa_db() as db:
        admin = await seed(db, resources=['organization', 'workflow', 'leave_balance', 'workflow_admin', 'leave'])
        member = await seed(db, tenant=admin.tenant_id, resources=['leave'])
        outsider = await seed(db, resources=['leave'])
        disabled = await seed(db, tenant=admin.tenant_id)
        (await db.get(OAUser, disabled.user_id)).status = 'disabled'
        await db.commit()
        options = await workflows.workbench_options(db, admin, resource='leave_balance', action='write')
        assert {u['id'] for u in options['users']} == {admin.user_id, member.user_id}
        assert member.depts[0] in {d['id'] for d in options['departments']}
        result = await balances.adjust(db, admin, BalanceAdjustment(operation_id='other-dept', expected_revision=0,
            user_id=member.user_id, leave_type='annual', year=2026, total=10, reason='Initialize'))
        await db.commit()
        assert (await balances.list_balances(db, admin, member.user_id))[0]['total'] == 10
        saved = await workflows.save_definition(db, admin, WorkflowSave(operation_id='other-workflow',
            department_id=member.depts[0], code='leave', name='Other department', definition=definition()))
        await db.commit()
        assert saved['id'] in {r['id'] for r in await workflows.list_definitions(db, admin)}
        assert await workflows.list_definitions(db, admin, available=True) == []
        with pytest.raises(AppException):
            await balances.list_balances(db, admin, outsider.user_id)
        with pytest.raises(AppException):
            await balances.adjust(db, admin, BalanceAdjustment(operation_id='disabled', expected_revision=0,
                user_id=disabled.user_id, leave_type='annual', year=2026, total=10, reason='Denied'))


async def test_department_manager_does_not_gain_organization_scope(oa_db):
    async with oa_db() as db:
        manager = await seed(db, resources=['workflow', 'leave_balance'])
        colleague = await seed(db, tenant=manager.tenant_id, department=manager.depts[0])
        other = await seed(db, tenant=manager.tenant_id)
        await db.commit()
        options = await workflows.workbench_options(db, manager, resource='leave_balance', action='write')
        assert {u['id'] for u in options['users']} == {manager.user_id, colleague.user_id}
        with pytest.raises(AppException):
            await balances.adjust(db, manager, BalanceAdjustment(operation_id='denied', expected_revision=0,
                user_id=other.user_id, leave_type='annual', year=2026, total=10, reason='Denied'))


async def test_organization_permission_alone_does_not_grant_balance_management(oa_db):
    async with oa_db() as db:
        admin = await seed(db, resources=['organization'])
        await db.commit()
        with pytest.raises(AppException):
            await workflows.workbench_options(db, admin, resource='leave_balance', action='write')


async def test_contract_reviewers_use_current_permissions_and_tenant(oa_db):
    async with oa_db() as db:
        owner = await seed(db, resources=['contract'])
        reviewer = await seed(db, tenant=owner.tenant_id, resources=['contract'])
        unqualified = await seed(db, tenant=owner.tenant_id)
        disabled = await seed(db, tenant=owner.tenant_id, resources=['contract'])
        (await db.get(OAUser, disabled.user_id)).status = 'disabled'
        await seed(db, resources=['contract'])
        await db.commit()
        assert {r['id'] for r in await contracts.reviewer_options(db, owner)} == {owner.user_id, reviewer.user_id}
        with pytest.raises(AppException):
            await contracts.reviewer_options(db, unqualified)


async def test_cross_department_administration_keeps_business_scope(oa_db):
    from app.services import oa_handoff_service as handoff, oa_notification_service as notifications
    from app.services import oa_ticket_service as tickets
    from app.schemas.oa_ticket import TicketRuleSave
    from tests.api.test_oa_approval_modes import submitted
    async with oa_db() as db:
        _, _, _, applicant, _ = await submitted(db)
        admin = await seed(db, tenant=applicant.tenant_id,
            resources=['organization', 'workflow_admin', 'notification_admin', 'ticket_admin'])
        manager = await seed(db, tenant=applicant.tenant_id, department=admin.depts[0],
            resources=['workflow_admin', 'notification_admin', 'ticket_admin'])
        handler = await seed(db, tenant=applicant.tenant_id, department=applicant.depts[0],
            resources=['ticket_handle'])
        await db.commit()
        assert len(await handoff.list_instances(db, admin)) == 1
        assert await handoff.list_instances(db, manager) == []
        assert (await notifications.get_contact(db, admin, applicant.user_id))['user_id'] == applicant.user_id
        with pytest.raises(AppException):
            await notifications.get_contact(db, manager, applicant.user_id)
        rule = TicketRuleSave(operation_id='cross-dept-rule', department_id=applicant.depts[0],
            code='device', category='device', impact='*', queue='support', assignee_id=handler.user_id)
        saved = await tickets.save_rule(db, admin, rule)
        await db.commit()
        assert saved.result['id'] in {row['id'] for row in await tickets.list_rules(db, admin, applicant.depts[0])}
        with pytest.raises(AppException):
            await tickets.list_rules(db, manager, applicant.depts[0])


async def test_read_only_and_role_names_do_not_grant_cross_department_writes(oa_db):
    from app.services.oa_access_service import authorize_oa, OAAccessTarget
    from app.models.identity import OARolePermission, OAPermission, OAUserRole
    from sqlalchemy import delete, select
    async with oa_db() as db:
        admin = await seed(db, resources=['organization', 'leave_balance'])
        member = await seed(db, tenant=admin.tenant_id)
        role_id = await db.scalar(select(OAUserRole.role_id).where(OAUserRole.user_id == admin.user_id))
        permission_id = await db.scalar(select(OAPermission.id).where(OAPermission.resource == 'leave_balance',
            OAPermission.action == 'write', OAPermission.scope == 'department'))
        await db.execute(delete(OARolePermission).where(OARolePermission.role_id == role_id,
            OARolePermission.permission_id == permission_id))
        await db.commit()
        options = await workflows.workbench_options(db, admin, resource='leave_balance')
        assert member.user_id in {row['id'] for row in options['users']}
        with pytest.raises(AppException):
            await workflows.workbench_options(db, admin, resource='leave_balance', action='write')
        manager = await seed(db, tenant=admin.tenant_id, resources=['leave_balance'])
        manager.roles = ['admin']
        await db.commit()
        with pytest.raises(AppException):
            await authorize_oa(db, manager, 'leave_balance', 'write',
                target=OAAccessTarget(admin.tenant_id, member.user_id, member.depts[0]))
