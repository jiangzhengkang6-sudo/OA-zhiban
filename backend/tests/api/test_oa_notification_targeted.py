"""An operator's single-business probe must leave the remaining queue untouched."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.oa_notification import OANotificationDelivery
from app.models.oa_workflow import OAWorkflowOutbox
from app.services import oa_notification_service as service, oa_notification_worker as worker
from tests.api.test_oa_notification import setup
from tests.api.test_oa_ticket import create
from tests.oa_support import oa_db


async def test_targeted_dispatch_and_claim_do_not_drain_or_expire_other_rows(oa_db):
    async with oa_db() as db:
        handler, owner = await setup(db)
        await service.save_contact(db, handler, handler.user_id, email='member@example.test',
                                   enabled=True, operation_id='consent')
        for key in ('older', 'selected', 'unrelated'):
            await create(db, owner, key)
        outboxes = (await db.scalars(select(OAWorkflowOutbox).where(
            OAWorkflowOutbox.tenant_id == owner.tenant_id).order_by(OAWorkflowOutbox.created_at))).all()
        for row in outboxes[:2]:
            assert await service.dispatch(db, tenant_id=owner.tenant_id, outbox_id=row.id) == 1
        assert outboxes[2].status == 'PENDING'
        assert await service.dispatch(db, tenant_id='another-tenant', outbox_id=outboxes[2].id) == 0
        await db.commit()
        deliveries = (await db.scalars(select(OANotificationDelivery).where(
            OANotificationDelivery.tenant_id == owner.tenant_id,
            OANotificationDelivery.channel == 'smtp').order_by(OANotificationDelivery.created_at))).all()
        older, selected = deliveries
        older.state = 'PROCESSING'
        older.lease_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
        selected_id, older_id = selected.id, older.id
    assert await worker.claim_one(oa_db, tenant_id='another-tenant', delivery_id=selected_id) is None
    claim = await worker.claim_one(oa_db, tenant_id=owner.tenant_id, delivery_id=selected_id)
    assert claim['id'] == selected_id
    assert await worker.claim_one(oa_db, tenant_id=owner.tenant_id, delivery_id=selected_id) is None
    assert await worker.prepare_send(oa_db, selected_id, claim['token'],
                                    now=datetime.now(timezone.utc) + timedelta(minutes=3)) is None
    async with oa_db() as db:
        assert (await db.get(OANotificationDelivery, selected_id)).state == 'UNKNOWN'
        assert (await db.get(OANotificationDelivery, older_id)).state == 'PROCESSING'
        assert (await db.get(OAWorkflowOutbox, outboxes[2].id)).status == 'PENDING'
