"""Bridge notification acceptance and delivery reconciliation use durable facts."""
import pytest
from sqlalchemy import delete, select
from pydantic import ValidationError

from app.adapters.builtin_gateway import BuiltinGateway
from app.adapters.gateway import BridgeContext
from app.core.errors import AppException
from app.models.identity import OAPermission, OARolePermission, OAUserRole
from app.models.oa_workflow import OAWorkflowEvent, OAWorkflowOutbox, OAWorkflowOperation
from app.models.oa_notification import OANotification, OANotificationDelivery
from app.core.context import get_trace_id, set_trace_id
from app.services import oa_notification_service as notifications
from tests.oa_support import oa_db, seed


def command():
    return dict(user_id='', title='事项提醒', body='请登录系统核对', channel='oa_inbox',
        business_id='', idempotency_key='notify-once')


async def test_bridge_notification_replays_and_reads_actual_channel_state(oa_db):
    async with oa_db() as db:
        actor = await seed(db, resources=['notification'], scope='self')
        await db.commit()
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        values = {**command(), 'user_id': actor.user_id}
        result = await gateway.notify(values)
        await db.commit()
        assert result['status'] == 'PENDING'
        assert await gateway.notify(values) == result
        await notifications.dispatch(db, tenant_id=actor.tenant_id)
        await db.commit()
        inbox = await notifications.list_inbox(db, actor)
        assert len(inbox) == 1
        state = await gateway.get_notification_result('notify-once')
        assert state['status'] == 'ACCEPTED'
        assert state['delivered'] is True
        assert state['channels']['inbox']['state'] == 'ACCEPTED'
        assert state['channels']['smtp']['state'] == 'PENDING'
        assert state['channels']['smtp']['attempts'] == []
        assert await gateway.get_notification_result('missing') is None


async def test_notification_reconciliation_rechecks_current_permission(oa_db):
    async with oa_db() as db:
        actor = await seed(db, resources=['notification'], scope='self')
        await db.commit()
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        await gateway.notify({**command(), 'user_id': actor.user_id})
        await db.commit()
        await db.execute(delete(OARolePermission).where(
            OARolePermission.tenant_id == actor.tenant_id,
            OARolePermission.role_id.in_(select(OAUserRole.role_id).where(OAUserRole.user_id == actor.user_id)),
            OARolePermission.permission_id.in_(select(OAPermission.id).where(OAPermission.resource == 'notification'))))
        await db.commit()
        with pytest.raises(AppException) as error:
            await gateway.get_notification_result('notify-once')
        assert error.value.http_status == 403


@pytest.mark.parametrize('source', [None, {}, {'kind': 'intent', 'recipient_id': 'other'}])
async def test_legacy_notification_without_trusted_source_is_explicitly_unavailable(oa_db, source):
    async with oa_db() as db:
        actor = await seed(db, resources=['notification'], scope='self')
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        await gateway.notify({**command(), 'user_id': actor.user_id})
        operation = await db.scalar(select(OAWorkflowOperation).where(
            OAWorkflowOperation.tenant_id == actor.tenant_id, OAWorkflowOperation.kind == 'notification.intent'))
        result = {key: value for key, value in operation.result.items() if key != 'source'}
        if source is not None:
            result['source'] = source
        operation.result = result
        await db.commit()
        with pytest.raises(AppException) as error:
            await gateway.get_notification_result('notify-once')
        assert error.value.http_status == 503
        await notifications.dispatch(db, tenant_id=actor.tenant_id)
        await db.commit()
        assert await notifications.list_inbox(db, actor) == []


async def test_notification_cannot_reference_unreadable_business_source(oa_db):
    async with oa_db() as db:
        actor = await seed(db, resources=['notification'], scope='self')
        await db.commit()
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        with pytest.raises(AppException):
            await gateway.notify({**command(), 'user_id': actor.user_id, 'business_id': 'unknown-business'})


@pytest.mark.parametrize('change', [{'idempotency_key': ''}, {'actor_id': 'forged'}])
async def test_notification_bridge_validates_formal_input(oa_db, change):
    async with oa_db() as db:
        actor = await seed(db, resources=['notification'], scope='self')
        await db.commit()
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        with pytest.raises(ValidationError):
            await gateway.notify({**command(), 'user_id': actor.user_id, **change})


async def test_notification_uses_bridge_trace_and_restores_caller_context(oa_db):
    async with oa_db() as db:
        actor = await seed(db, resources=['notification'], scope='self')
        await db.commit()
        previous = get_trace_id()
        set_trace_id('caller-trace')
        try:
            gateway = BuiltinGateway(BridgeContext(actor=actor, session=db, trace_id='intent-trace'))
            await gateway.notify({**command(), 'user_id': actor.user_id})
            event = await db.scalar(select(OAWorkflowEvent).where(
                OAWorkflowEvent.tenant_id == actor.tenant_id, OAWorkflowEvent.action == 'notification.intent'))
            assert event.trace_id == 'intent-trace'
            assert get_trace_id() == 'caller-trace'
        finally:
            set_trace_id(previous)


async def test_referenced_leave_rechecks_source_before_dispatch_and_reconciliation(oa_db):
    from tests.contracts.test_builtin_leave_gateway import draft_fixture
    async with oa_db() as db:
        _, actor, _, draft = await draft_fixture(db)
        gateway = BuiltinGateway(BridgeContext(actor=actor, session=db))
        # Notification permission alone never grants access to a formal source.
        denied_actor = await seed(db, tenant=actor.tenant_id, resources=['notification'], scope='self')
        denied_gateway = BuiltinGateway(BridgeContext(actor=denied_actor, session=db))
        await db.commit()
        with pytest.raises(AppException):
            await denied_gateway.notify({**command(), 'user_id': denied_actor.user_id, 'business_id': draft['id']})
        # Grant the owner's notification permission through an existing seeded role.
        from app.models.identity import OARolePermission
        role_id = await db.scalar(select(OAUserRole.role_id).where(OAUserRole.user_id == actor.user_id))
        for action in ('read', 'write'):
            permission = await db.scalar(select(OAPermission).where(OAPermission.resource == 'notification',
                OAPermission.action == action, OAPermission.scope == 'self'))
            db.add(OARolePermission(tenant_id=actor.tenant_id, role_id=role_id, permission_id=permission.id))
        await db.commit()
        await gateway.notify({**command(), 'user_id': actor.user_id, 'business_id': draft['business_no']})
        await db.commit()
        await db.execute(delete(OARolePermission).where(OARolePermission.tenant_id == actor.tenant_id,
            OARolePermission.role_id == role_id, OARolePermission.permission_id.in_(
                select(OAPermission.id).where(OAPermission.resource == 'leave'))))
        await db.commit()
        await notifications.dispatch(db, tenant_id=actor.tenant_id)
        await db.commit()
        assert await notifications.list_inbox(db, actor) == []
        deliveries = (await db.scalars(select(OANotificationDelivery).join(OANotification,
            OANotificationDelivery.notification_id == OANotification.id).join(OAWorkflowOutbox,
            OANotification.source_outbox_id == OAWorkflowOutbox.id).join(OAWorkflowEvent,
            OAWorkflowOutbox.event_id == OAWorkflowEvent.id).where(
            OANotificationDelivery.tenant_id == actor.tenant_id, OAWorkflowEvent.action == 'notification.intent'))).all()
        assert len(deliveries) == 2
        assert all(row.state == 'CANCELLED' for row in deliveries)
        with pytest.raises(AppException) as error:
            await gateway.get_notification_result('notify-once')
        assert error.value.http_status == 403
