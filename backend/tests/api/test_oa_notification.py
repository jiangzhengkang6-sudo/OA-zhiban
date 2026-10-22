from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from sqlalchemy import select,func,delete
from app.core.errors import AppException
from tests.oa_support import oa_db,seed


async def setup(db):
    from app.schemas.oa_ticket import TicketRuleSave
    from app.services import oa_ticket_service as tickets
    handler=await seed(db,resources=['ticket_handle','ticket_admin','notification','notification_admin'])
    owner=await seed(db,tenant=handler.tenant_id,department=handler.depts[0],resources=['ticket','notification'],scope='self')
    await tickets.save_rule(db,handler,TicketRuleSave(operation_id='rule',department_id=handler.depts[0],code='default',
        category='*',impact='*',queue='服务台',assignee_id=handler.user_id,priority=1,enabled=True))
    await db.commit()
    return handler,owner


async def enqueue(db,owner):
    from tests.api.test_oa_ticket import create
    from app.services import oa_notification_service as notifications
    row,_,_=await create(db,owner,uuid4().hex)
    await notifications.dispatch(db,tenant_id=owner.tenant_id)
    await db.commit()
    return row


async def test_outbox_inbox_unique_and_read_idempotent(oa_db):
    from app.services import oa_notification_service as service
    from app.models.oa_notification import OANotification,OANotificationDelivery
    async with oa_db() as db:
        handler,owner=await setup(db)
        ticket=await enqueue(db,owner)
        await service.dispatch(db,tenant_id=owner.tenant_id)
        await db.commit()
        items=await service.list_inbox(db,handler)
        assert len(items)==1 and items[0]['read_at'] is None
        assert 'summary' not in items[0] and 'email' not in str(items[0])
        assert await db.scalar(select(func.count()).select_from(OANotification).where(OANotification.tenant_id==owner.tenant_id))==1
        assert await db.scalar(select(func.count()).select_from(OANotificationDelivery).where(OANotificationDelivery.tenant_id==owner.tenant_id))==2
        first=await service.mark_read(db,handler,items[0]['id'])
        second=await service.mark_read(db,handler,items[0]['id'])
        assert first['read_at']==second['read_at']
        await db.commit()
        with pytest.raises(AppException): await service.mark_read(db,owner,items[0]['id'])


async def test_latest_contact_and_revocation_cancel_before_delivery(oa_db):
    from app.services import oa_notification_service as service,oa_notification_worker as worker
    from app.models.identity import OAUserRole
    from app.models.oa_notification import OANotificationDelivery
    async with oa_db() as db:
        handler,owner=await setup(db)
        await service.save_contact(db,handler,handler.user_id,email='old@example.test',enabled=True,operation_id='old')
        await db.commit()
        await enqueue(db,owner)
        await service.save_contact(db,handler,handler.user_id,email='new@example.test',enabled=True,operation_id='new')
        await db.commit()
    claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id)
    assert claim['recipient']=='new@example.test'
    await worker.complete(oa_db,claim['id'],claim['token'],'ACCEPTED')
    async with oa_db() as db:
        await enqueue(db,owner)
    async with oa_db() as db:
        await db.execute(delete(OAUserRole).where(OAUserRole.tenant_id==handler.tenant_id,OAUserRole.user_id==handler.user_id))
        await db.commit()
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id) is None
    async with oa_db() as db:
        rows=(await db.scalars(select(OANotificationDelivery).where(OANotificationDelivery.tenant_id==owner.tenant_id,
            OANotificationDelivery.channel=='smtp'))).all()
        assert sorted(r.state for r in rows)==['ACCEPTED','CANCELLED']
        with pytest.raises(AppException): await service.list_inbox(db,handler)


async def test_unknown_no_automatic_retry_and_explicit_admin_recovery(oa_db):
    from app.services import oa_notification_service as service,oa_notification_worker as worker
    from app.models.oa_notification import OANotificationDelivery,OANotificationAttempt
    async with oa_db() as db:
        handler,owner=await setup(db)
        await service.save_contact(db,handler,handler.user_id,email='member@example.test',enabled=True,operation_id='contact')
        await db.commit()
        await enqueue(db,owner)
    now=datetime.now(timezone.utc)
    first=await worker.claim_one(oa_db,tenant_id=owner.tenant_id,now=now)
    assert first
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,now=now) is None
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,now=now+timedelta(minutes=5)) is None
    async with oa_db() as db:
        delivery=await db.get(OANotificationDelivery,first['id'])
        assert delivery.state=='UNKNOWN'
        with pytest.raises(AppException):
            await service.retry_unknown(db,owner,first['id'],note='已核对，请重试',operation_id='retry')
        await db.rollback()
        await service.retry_unknown(db,handler,first['id'],note='已核对，确认可能重复，显式重试',operation_id='retry')
        await db.commit()
    second=await worker.claim_one(oa_db,tenant_id=owner.tenant_id,now=now+timedelta(minutes=6))
    assert second['message_id']==first['message_id'] and second['token']!=first['token']
    assert not await worker.complete(oa_db,first['id'],first['token'],'ACCEPTED')
    assert await worker.complete(oa_db,second['id'],second['token'],'ACCEPTED')
    async with oa_db() as db:
        attempts=(await db.scalars(select(OANotificationAttempt).where(OANotificationAttempt.delivery_id==first['id']).order_by(OANotificationAttempt.number))).all()
        assert [a.state for a in attempts]==['UNKNOWN','ACCEPTED']


async def test_temporary_failures_bounded_and_permanent_failure_stops(oa_db):
    from app.services import oa_notification_service as service,oa_notification_worker as worker
    from app.models.oa_notification import OANotificationDelivery
    async with oa_db() as db:
        handler,owner=await setup(db)
        await service.save_contact(db,handler,handler.user_id,email='member@example.test',enabled=True,operation_id='contact')
        await db.commit()
        await enqueue(db,owner)
    now=datetime.now(timezone.utc)
    for number in range(4):
        claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id,now=now)
        assert claim
        await worker.complete(oa_db,claim['id'],claim['token'],'TEMPORARY',now=now)
        assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,now=now) is None
        now+=timedelta(minutes=[1,5,30,30][number])
    async with oa_db() as db:
        assert (await db.get(OANotificationDelivery,claim['id'])).state=='FAILED'
        await enqueue(db,owner)
    claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id,now=now)
    await worker.complete(oa_db,claim['id'],claim['token'],'PERMANENT',now=now)
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,now=now+timedelta(days=1)) is None


async def test_email_is_minimal_and_business_survives_delivery_failure(oa_db):
    from app.services import oa_notification_service as service,oa_notification_worker as worker
    from app.models.oa_ticket import OATicket
    async with oa_db() as db:
        handler,owner=await setup(db)
        await service.save_contact(db,handler,handler.user_id,email='member@example.test',enabled=True,operation_id='contact')
        await db.commit()
        ticket=await enqueue(db,owner)
    captured=[]
    def fail(claim):
        captured.append(claim)
        return 'UNKNOWN'
    await worker.run_once(oa_db,tenant_id=owner.tenant_id,sender=fail)
    assert len(captured)==1 and '电脑' not in captured[0]['body']
    assert 'member@example.test' not in captured[0]['body']
    async with oa_db() as db:
        assert (await db.get(OATicket,ticket['id'])).state=='OPEN'
        inbox=await service.list_inbox(db,handler)
        assert inbox[0]['smtp_state']=='UNKNOWN'
        assert inbox[0]['delivered'] is True


async def test_send_preflight_refreshes_address_and_fences_revoked_claim(oa_db):
    from app.services import oa_notification_service as service,oa_notification_worker as worker
    from app.models.identity import OAUserRole
    from app.models.oa_notification import OANotificationDelivery,OANotificationAttempt
    async with oa_db() as db:
        handler,owner=await setup(db)
        await service.save_contact(db,handler,handler.user_id,email='old@example.test',enabled=True,operation_id='contact')
        await db.commit()
        await enqueue(db,owner)
    claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id)
    async with oa_db() as db:
        await service.save_contact(db,handler,handler.user_id,email='current@example.test',enabled=True,operation_id='changed')
        await db.commit()
    prepared=await worker.prepare_send(oa_db,claim['id'],claim['token'])
    assert prepared['recipient']=='current@example.test'
    async with oa_db() as db:
        await db.execute(delete(OAUserRole).where(OAUserRole.tenant_id==handler.tenant_id,OAUserRole.user_id==handler.user_id))
        await db.commit()
    assert await worker.prepare_send(oa_db,claim['id'],claim['token']) is None
    assert not await worker.complete(oa_db,claim['id'],claim['token'],'ACCEPTED')
    async with oa_db() as db:
        assert (await db.get(OANotificationDelivery,claim['id'])).state=='CANCELLED'
        attempt=await db.scalar(select(OANotificationAttempt).where(OANotificationAttempt.token==claim['token']))
        assert attempt.state=='PERMANENT' and attempt.finished_at


async def test_disabled_smtp_recovers_expired_leases_without_sending(oa_db,monkeypatch):
    from app.services import oa_notification_service as service,oa_notification_worker as worker
    from app.models.oa_notification import OANotificationDelivery
    from types import SimpleNamespace
    async with oa_db() as db:
        handler,owner=await setup(db)
        await service.save_contact(db,handler,handler.user_id,email='member@example.test',enabled=True,operation_id='contact')
        await db.commit()
        await enqueue(db,owner)
    claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id,now=datetime.now(timezone.utc)-timedelta(minutes=5))
    monkeypatch.setattr(worker,'get_settings',lambda:SimpleNamespace(smtp_enabled=False))
    assert await worker.run_once(oa_db,tenant_id=owner.tenant_id)==0
    async with oa_db() as db:
        assert (await db.get(OANotificationDelivery,claim['id'])).state=='UNKNOWN'


async def test_review_note_durable_and_read_is_audited(oa_db):
    from app.services import oa_notification_service as service,oa_notification_worker as worker
    from app.models.oa_workflow import OAWorkflowEvent
    async with oa_db() as db:
        handler,owner=await setup(db)
        await service.save_contact(db,handler,handler.user_id,email='member@example.test',enabled=True,operation_id='contact')
        await db.commit()
        await enqueue(db,owner)
    claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id)
    await worker.complete(oa_db,claim['id'],claim['token'],'UNKNOWN')
    async with oa_db() as db:
        inbox=await service.list_inbox(db,handler)
        await service.mark_read(db,handler,inbox[0]['id'])
        await service.mark_read(db,handler,inbox[0]['id'])
        await service.retry_unknown(db,handler,claim['id'],note='核对服务端日志后允许重试，可能重复',operation_id='review')
        await db.commit()
        rows=await service.list_deliveries(db,handler)
        assert rows[0]['reviews'][0]['note']=='核对服务端日志后允许重试，可能重复'
        assert rows[0]['reviews'][0]['reviewer_id']==handler.user_id
        events=(await db.scalars(select(OAWorkflowEvent).where(OAWorkflowEvent.tenant_id==owner.tenant_id))).all()
        assert len([e for e in events if e.action=='notification.read'])==1
        assert all('核对服务端日志' not in str(e.detail) for e in events)


@pytest.mark.parametrize('change',['resolve','move','disable_contact'])
async def test_terminal_move_and_disabled_contact_suppress_claim(oa_db,change):
    from app.services import oa_notification_service as service,oa_notification_worker as worker,oa_ticket_service as tickets
    from app.models.identity import OADepartment,OAMembership
    from app.models.oa_notification import OANotificationDelivery
    from app.schemas.oa_ticket import TicketHandleCommand
    async with oa_db() as db:
        handler,owner=await setup(db)
        await service.save_contact(db,handler,handler.user_id,email='member@example.test',enabled=True,operation_id='contact')
        await db.commit()
        ticket=await enqueue(db,owner)
    claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id)
    async with oa_db() as db:
        if change=='resolve':
            await tickets.handle(db,handler,ticket['id'],TicketHandleCommand(operation_id='resolve',expected_revision=1,action='resolve',note='完成'))
        elif change=='move':
            dept=OADepartment(tenant_id=owner.tenant_id,name='新部门')
            db.add(dept)
            await db.flush()
            (await db.get(OAMembership,(owner.tenant_id,handler.user_id))).department_id=dept.id
        else:
            await service.save_contact(db,handler,handler.user_id,email='member@example.test',enabled=False,operation_id='disabled')
        await db.commit()
    assert await worker.prepare_send(oa_db,claim['id'],claim['token']) is None
    async with oa_db() as db:
        assert (await db.get(OANotificationDelivery,claim['id'])).state=='CANCELLED'


async def test_outbox_handoff_rollback_does_not_lose_business(oa_db,monkeypatch):
    from tests.api.test_oa_ticket import create
    from app.services import oa_notification_service as service,oa_notification_source as sources
    from app.models.oa_workflow import OAWorkflowOutbox
    from app.models.oa_notification import OANotification
    from app.models.oa_ticket import OATicket
    async with oa_db() as db:
        _,owner=await setup(db)
        ticket,_,_=await create(db,owner,'atomic')
        async def fail(*args): raise RuntimeError('handoff failure')
        with monkeypatch.context() as patch:
            patch.setattr(sources,'allowed',fail)
            with pytest.raises(RuntimeError): await service.dispatch(db,tenant_id=owner.tenant_id)
        await db.rollback()
        assert (await db.get(OATicket,ticket['id'])).state=='OPEN'
        outbox=await db.scalar(select(OAWorkflowOutbox).where(OAWorkflowOutbox.tenant_id==owner.tenant_id))
        assert outbox.status=='PENDING'
        assert await db.scalar(select(func.count()).select_from(OANotification).where(OANotification.tenant_id==owner.tenant_id))==0
        assert await service.dispatch(db,tenant_id=owner.tenant_id)==1
        await db.commit()


async def test_workflow_terminal_rechecks_inbox_and_pending_smtp(oa_db):
    from tests.api.test_oa_approval_modes import submitted
    from app.services import oa_notification_service as service,oa_notification_worker as worker,oa_approval_service as approvals
    from app.models.identity import OARolePermission,OAUserRole,OAPermission
    from app.schemas.oa_workflow import DecideNodeCommand
    async with oa_db() as db:
        first,_,_,actor,_=await submitted(db)
        # Grant only the explicit new resource; existing roles receive no implicit upgrade.
        role_id=await db.scalar(select(OAUserRole.role_id).where(OAUserRole.tenant_id==actor.tenant_id,OAUserRole.user_id==first.user_id))
        for action in ('read','write'):
            permission=await db.scalar(select(OAPermission).where(OAPermission.resource=='notification',OAPermission.action==action,OAPermission.scope=='self'))
            if not permission:
                permission=OAPermission(resource='notification',action=action,scope='self')
                db.add(permission)
                await db.flush()
            db.add(OARolePermission(tenant_id=actor.tenant_id,role_id=role_id,permission_id=permission.id))
        await db.commit()
        await service.save_contact(db,first,first.user_id,email='approver@example.test',enabled=True,operation_id='contact')
        await db.commit()
        await service.dispatch(db,tenant_id=actor.tenant_id)
        await db.commit()
        items=await service.list_inbox(db,first)
        assert len(items)==1 and items[0]['resource']=='approval'
        node=(await approvals.list_items(db,first,'pending'))[0]['node_id']
        await approvals.decide(db,first,node,DecideNodeCommand(operation_id='done',expected_revision=1,action='approve',note='同意'))
        await db.commit()
        assert await service.list_inbox(db,first)==[]
        with pytest.raises(AppException): await service.mark_read(db,first,items[0]['id'])
        await db.rollback()
    assert await worker.claim_one(oa_db,tenant_id=actor.tenant_id) is None


async def test_unconfigured_first_page_does_not_starve_later_recipient(oa_db,monkeypatch):
    from app.services import oa_notification_service as service,oa_notification_worker as worker,oa_ticket_service as tickets
    from app.schemas.oa_ticket import TicketRuleSave
    async with oa_db() as db:
        handler,owner=await setup(db)
        for _ in range(100):
            await enqueue(db,owner)
        available=await seed(db,tenant=owner.tenant_id,department=handler.depts[0],resources=['ticket_handle','notification'])
        await service.save_contact(db,available,available.user_id,email='available@example.test',enabled=True,operation_id='contact')
        await db.commit()
        await enqueue(db,owner)
        from app.models.oa_notification import OANotification
        latest=await db.scalar(select(OANotification).where(OANotification.tenant_id==owner.tenant_id).order_by(OANotification.created_at.desc()))
        latest.recipient_id=available.user_id
        latest.department_id=handler.depts[0]
        await db.commit()
    async def allow_source(*args): return True
    monkeypatch.setattr('app.services.oa_notification_worker.sources.allowed',allow_source)
    claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id)
    assert claim and claim['recipient']=='available@example.test'
