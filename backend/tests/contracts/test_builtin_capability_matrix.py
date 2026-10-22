"""Executable cross-cutting checks for all 13 core and two auxiliary methods."""
from copy import deepcopy

import pytest
from sqlalchemy import func, select

from app.adapters.builtin_gateway import BuiltinGateway, CORE_CAPABILITIES, AUXILIARY_CAPABILITIES
from app.adapters.gateway import BridgeContext
from app.core.errors import AppException
from app.models.identity import OAUser
from app.models.oa_workflow import OAWorkflowOperation
from app.services import oa_ticket_service as tickets
from tests.contracts.test_builtin_leave_gateway import draft_fixture, confirmed, edit_values, submit_values
from tests.contracts.test_builtin_notification_gateway import command as notification_command
from tests.api.test_oa_ticket import setup as ticket_setup, proposal
from tests.oa_support import oa_db, seed


METHOD_ARGS = {
    'capabilities': (), 'get_user_context': (), 'get_leave_case': ('missing',),
    'get_leave_balance': (), 'get_approval_route': ('missing',),
    'create_or_update_approval': ({},), 'get_approval_result': ('missing',),
    'edit_leave_case': ({},), 'get_leave_edit_result': ('missing',),
    'create_or_merge_ticket': ({},), 'get_ticket_result': ('missing',),
    'notify': ({},), 'get_notification_result': ('missing',),
    'get_ticket_status': ('missing',), 'get_field_dict': (),
}


def test_matrix_covers_every_advertised_method():
    assert set(METHOD_ARGS) == set(CORE_CAPABILITIES + AUXILIARY_CAPABILITIES)
    assert len(CORE_CAPABILITIES) == 13 and len(AUXILIARY_CAPABILITIES) == 2


@pytest.mark.parametrize('method', METHOD_ARGS)
async def test_every_capability_rejects_disabled_cached_identity(oa_db, monkeypatch, method):
    from app.adapters import factory
    monkeypatch.setattr(factory, 'get_adapter', lambda: pytest.fail('formal gateway used legacy adapter'))
    async with oa_db() as db:
        actor = await seed(db)
        await db.commit()
        async with oa_db() as mutation:
            user = await mutation.get(OAUser, actor.user_id)
            user.status = 'disabled'
            await mutation.commit()
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        with pytest.raises(AppException) as denied:
            await getattr(gateway, method)(*METHOD_ARGS[method])
        assert denied.value.http_status == 401
        assert await db.scalar(select(func.count()).select_from(OAWorkflowOperation).where(
            OAWorkflowOperation.tenant_id == actor.tenant_id)) == 0


@pytest.mark.parametrize('method', ['get_leave_case', 'get_approval_route', 'get_leave_balance'])
@pytest.mark.parametrize('foreign_tenant', [False, True])
async def test_leave_read_capabilities_reject_unscoped_other_owner(oa_db, method, foreign_tenant):
    async with oa_db() as db:
        _, owner, _, draft = await draft_fixture(db)
        reader = await seed(db, tenant=None if foreign_tenant else owner.tenant_id,
            resources=['leave', 'leave_balance'], scope='self')
        await db.commit()
        gateway = BuiltinGateway(BridgeContext(actor=reader, session=db))
        with pytest.raises(AppException) as denied:
            await getattr(gateway, method)(owner.user_id if method == 'get_leave_balance' else draft['id'])
        assert denied.value.http_status in {403, 404}


async def test_leave_detail_balance_and_missing_result_reads_do_not_write(oa_db):
    async with oa_db() as db:
        _, actor, _, draft = await draft_fixture(db)
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        before = await db.scalar(select(func.count()).select_from(OAWorkflowOperation))
        assert (await gateway.get_leave_case(draft['business_no']))['id'] == draft['id']
        assert (await gateway.get_leave_balance(actor.user_id, 'annual'))[0]['total'] == 5
        with pytest.raises(AppException) as missing:
            await gateway.get_leave_balance(actor.user_id, 'missing')
        assert missing.value.http_status == 404
        assert await gateway.get_approval_result('not-committed') is None
        assert await gateway.get_leave_edit_result('not-committed') is None
        assert await db.scalar(select(func.count()).select_from(OAWorkflowOperation)) == before


@pytest.mark.parametrize(('method', 'action', 'builder'), [
    ('create_or_update_approval', 'leave.submit', submit_values),
    ('edit_leave_case', 'leave.edit', edit_values),
])
async def test_leave_gateway_same_key_changed_content_requires_new_confirmation(oa_db, method, action, builder):
    async with oa_db() as db:
        _, actor, _, draft = await draft_fixture(db)
        values = builder(draft)
        gateway = await confirmed(db, actor, action, values)
        result = await getattr(gateway, method)(values)
        await db.commit()
        changed = deepcopy(values)
        if method == 'edit_leave_case':
            changed['fields']['reason'] = 'different content'
        else:
            changed['review_route_hash'] = '0' * 64 if values.get('review_route_hash') != '0' * 64 else '1' * 64
        with pytest.raises(AppException) as conflict:
            await getattr(gateway, method)(changed)
        assert conflict.value.http_status in {409, 422}
        await db.rollback()
        assert await getattr(gateway, method)(values) == result


async def test_notification_same_key_changed_payload_conflicts_and_result_is_read_only(oa_db):
    async with oa_db() as db:
        actor = await seed(db, resources=['notification'], scope='self')
        await db.commit()
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        values = {**notification_command(), 'user_id': actor.user_id}
        first = await gateway.notify(values)
        await db.commit()
        with pytest.raises(AppException) as conflict:
            await gateway.notify({**values, 'body': 'different content'})
        assert conflict.value.http_status == 409
        await db.rollback()
        assert await gateway.notify(values) == first
        count = await db.scalar(select(func.count()).select_from(OAWorkflowOperation))
        assert await gateway.get_notification_result('missing') is None
        assert (await gateway.get_notification_result(values['idempotency_key']))['status'] == 'PENDING'
        assert await db.scalar(select(func.count()).select_from(OAWorkflowOperation)) == count


async def test_ticket_gateway_changed_confirmation_and_foreign_result_are_rejected(oa_db):
    async with oa_db() as db:
        _, actor = await ticket_setup(db)
        values = proposal('matrix-ticket')
        confirmation = await tickets.prepare(db, actor, values)
        await db.commit()
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db,
            confirmation_id=confirmation['confirmation_id']))
        first = await gateway.create_or_merge_ticket(values)
        await db.commit()
        with pytest.raises(AppException) as conflict:
            await gateway.create_or_merge_ticket(values.model_copy(update={'summary': 'different content'}))
        assert conflict.value.http_status in {409, 422}
        await db.rollback()
        assert await gateway.create_or_merge_ticket(values) == first
        outsider = await seed(db, tenant=actor.tenant_id, resources=['ticket'], scope='self')
        await db.commit()
        foreign = BuiltinGateway(BridgeContext(actor=outsider, session=db))
        assert await foreign.get_ticket_result('matrix-ticket') is None
        with pytest.raises(AppException) as denied:
            await foreign.get_ticket_status(first['id'])
        assert denied.value.http_status in {403, 404}
