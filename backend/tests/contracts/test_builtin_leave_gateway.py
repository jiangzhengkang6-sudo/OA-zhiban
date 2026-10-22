"""Formal bridge regression tests, using only the approved isolated database."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select

from app.adapters.builtin_gateway import BuiltinGateway
from app.adapters.gateway import BridgeContext
from app.core.errors import AppException
from app.models.identity import OAPermission, OARolePermission, OAUserRole
from app.models.oa_bridge import OABridgeConfirmation
from app.models.oa_workflow import OAWorkflowEvent, OAWorkflowOperation
from app.schemas.oa_leave import BalanceAdjustment, LeaveDraftCreate, LeaveDraftPatch, SubmitLeaveCommand
from app.services import oa_balance_service as balances, oa_confirmation_service as confirmations
from app.services import oa_leave_service as leaves, oa_workflow_service as workflows
from tests.api.test_oa_leave_lifecycle import fields, setup_leave
from tests.oa_support import oa_db, seed


async def draft_fixture(db):
    admin, actor, workflow = await setup_leave(db)
    draft = await leaves.create_draft(db, actor, LeaveDraftCreate(
        operation_id='draft', workflow_definition_id=workflow, fields=fields()))
    await balances.adjust(db, admin, BalanceAdjustment(operation_id='quota', expected_revision=0,
        user_id=actor.user_id, leave_type='annual', year=2026, total=5, reason='测试额度'))
    await db.commit()
    return admin, actor, workflow, draft.result


def submit_values(draft):
    return dict(action='submit', business_id=draft['id'], thread_id=None,
        operation_id='submit', expected_revision=1, requested_submission_version=1)


def edit_values(draft):
    return dict(business_id=draft['id'], thread_id=None, operation_id='edit',
        expected_revision=1, fields=fields('2026-10-20', '2026-10-21').model_dump(mode='json'))


async def confirmed(db, actor, action, values, *, object_id=None):
    binding = await confirmations.issue(db, actor, thread_id=values['thread_id'], action=action,
        object_id=object_id or values['business_id'], object_version=values['expected_revision'], payload=values)
    await db.commit()
    return BuiltinGateway(BridgeContext(actor=actor, session=db, trace_id='trace-formal-bridge',
        confirmation_id=binding['confirmation_id']))


@pytest.mark.parametrize('method,values', [
    ('create_or_update_approval', submit_values), ('edit_leave_case', edit_values)])
async def test_leave_writes_reject_missing_server_confirmation(oa_db, method, values):
    async with oa_db() as db:
        _, actor, _, draft = await draft_fixture(db)
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        with pytest.raises(AppException) as error:
            await getattr(gateway, method)(values(draft))
        assert error.value.http_status == 403
        assert (await leaves.detail(db, actor, draft['id']))['revision'] == 1


async def test_confirmed_leave_submit_and_read_only_result_replay(oa_db):
    async with oa_db() as db:
        _, actor, _, draft = await draft_fixture(db)
        values = submit_values(draft)
        gateway = await confirmed(db, actor, 'leave.submit', values)
        first = await gateway.create_or_update_approval(values)
        await db.commit()
        assert first['state'] == 'IN_REVIEW'
        assert await gateway.create_or_update_approval(values) == first
        assert await gateway.get_approval_result('submit') == first
        assert await gateway.get_approval_result('missing') is None
        count = await db.scalar(select(func.count()).select_from(OAWorkflowOperation).where(
            OAWorkflowOperation.tenant_id == actor.tenant_id, OAWorkflowOperation.kind == 'leave.submit'))
        assert count == 1
        confirmation = await db.get(OABridgeConfirmation, gateway.context.confirmation_id)
        assert confirmation.consumed_operation_id
        event = await db.scalar(select(OAWorkflowEvent).where(
            OAWorkflowEvent.operation_id == confirmation.consumed_operation_id))
        assert event.trace_id == 'trace-formal-bridge'


async def test_confirmed_edit_preserves_input_and_confirmation_is_atomic(oa_db):
    async with oa_db() as db:
        _, actor, _, draft = await draft_fixture(db)
        values = edit_values(draft)
        original = deepcopy(values)
        gateway = await confirmed(db, actor, 'leave.edit', values)
        result = await gateway.edit_leave_case(values)
        await db.commit()
        assert values == original
        assert result['revision'] == 2
        assert await gateway.edit_leave_case(values) == result
        assert await gateway.get_leave_edit_result('edit') == result
        confirmation = await db.get(OABridgeConfirmation, gateway.context.confirmation_id)
        assert confirmation.consumed_operation_id


@pytest.mark.parametrize('kind', ['leave.submit', 'leave.edit'])
async def test_result_reads_reauthorize_current_resource(oa_db, kind):
    async with oa_db() as db:
        _, actor, _, draft = await draft_fixture(db)
        if kind == 'leave.submit':
            await leaves.submit(db, actor, draft['id'], SubmitLeaveCommand(
                operation_id='result', expected_revision=1, requested_submission_version=1))
        else:
            await leaves.update_draft(db, actor, draft['id'], LeaveDraftPatch(
                operation_id='result', expected_revision=1, fields=fields()))
        await db.commit()
        await db.execute(delete(OARolePermission).where(
            OARolePermission.tenant_id == actor.tenant_id,
            OARolePermission.role_id.in_(select(OAUserRole.role_id).where(OAUserRole.user_id == actor.user_id)),
            OARolePermission.permission_id.in_(select(OAPermission.id).where(OAPermission.resource == 'leave'))))
        await db.commit()
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        method = gateway.get_approval_result if kind == 'leave.submit' else gateway.get_leave_edit_result
        with pytest.raises(AppException) as error:
            await method('result')
        assert error.value.http_status == 403


async def test_expired_confirmation_cannot_change_draft_or_create_operation(oa_db):
    async with oa_db() as db:
        _, actor, _, draft = await draft_fixture(db)
        values = edit_values(draft)
        gateway = await confirmed(db, actor, 'leave.edit', values)
        confirmation = await db.get(OABridgeConfirmation, gateway.context.confirmation_id)
        confirmation.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()
        with pytest.raises(AppException):
            await gateway.edit_leave_case(values)
        assert (await leaves.detail(db, actor, draft['id']))['revision'] == 1
        assert await gateway.get_leave_edit_result('edit') is None


async def test_balance_retains_both_years_and_fields_come_from_published_workflow(oa_db):
    async with oa_db() as db:
        admin, actor, workflow, _ = await draft_fixture(db)
        await balances.adjust(db, admin, BalanceAdjustment(operation_id='next-year', expected_revision=0,
            user_id=actor.user_id, leave_type='annual', year=2027, total=6, reason='下年额度'))
        await db.commit()
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        assert {row['year'] for row in await gateway.get_leave_balance(actor.user_id, 'annual')} == {2026, 2027}
        published = (await gateway.get_field_dict())['workflows']
        assert [row['id'] for row in published] == [workflow]
        assert published[0]['form']['leave_types'] == ['annual', 'sick']
        assert published[0]['workflow_version'] == 1
        other = await seed(db, tenant=actor.tenant_id, resources=['leave'], scope='self')
        await db.commit()
        assert (await BuiltinGateway(BridgeContext(actor=other, session=db)).get_field_dict())['workflows'] == []


async def test_submitted_route_remains_on_its_frozen_workflow_version(oa_db):
    from app.schemas.oa_workflow import WorkflowSave, PublishWorkflow
    from tests.unit.test_oa_workflow_definition import definition
    async with oa_db() as db:
        admin, actor, workflow, draft = await draft_fixture(db)
        await leaves.submit(db, actor, draft['id'], SubmitLeaveCommand(
            operation_id='submit', expected_revision=1, requested_submission_version=1))
        await db.commit()
        package = definition()
        package['rules']['timeout_hours'] = 72
        await workflows.save_definition(db, admin, WorkflowSave(operation_id='change-template',
            expected_revision=2, department_id=admin.depts[0], code='leave', name='请假', definition=package), workflow)
        await workflows.publish_definition(db, admin, workflow, PublishWorkflow(operation_id='publish-two', expected_revision=3))
        await db.commit()
        result = await BuiltinGateway(BridgeContext(actor=actor, session=db)).get_approval_route(draft['id'])
        assert result['rule_version'] == '1'
        assert result['nodes'][0]['approver_id'] == admin.user_id


async def test_approval_decision_bridge_uses_current_seat_and_server_confirmation(oa_db):
    from app.services import oa_approval_service as approvals
    async with oa_db() as db:
        admin, actor, _, draft = await draft_fixture(db)
        await leaves.submit(db, actor, draft['id'], SubmitLeaveCommand(
            operation_id='submit', expected_revision=1, requested_submission_version=1))
        await db.commit()
        node = (await approvals.list_items(db, admin, 'pending'))[0]
        values = dict(action='approve', node_id=node['node_id'], operation_id='decide',
            expected_revision=node['revision'], thread_id=None, note='', reason_code='other',
            corrections=[], approval_note=None)
        gateway = await confirmed(db, admin, 'approval.decide', values, object_id=node['node_id'])
        result = await gateway.create_or_update_approval(values)
        await db.commit()
        assert result['state'] == 'APPROVED'
        assert await gateway.create_or_update_approval(values) == result
        assert await gateway.get_approval_result('decide') == result
