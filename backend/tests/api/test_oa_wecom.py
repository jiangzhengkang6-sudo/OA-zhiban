"""Real ledger/permission tests with fake sends, never contact the group."""
from datetime import datetime, timedelta, timezone
import asyncio
import pytest
from pydantic import SecretStr
from sqlalchemy import select, func
from app.core.config import Settings
from app.core.errors import AppException
from app.models.oa_notification import OANotificationDelivery, OANotificationAttempt
from app.services import oa_notification_service as service, oa_notification_worker as worker
from tests.oa_support import oa_db, seed
from tests.api.test_oa_notification import setup, enqueue


def route(monkeypatch,handler):
    settings=Settings(_env_file=None,wecom_enabled=True,wecom_tenant_id=handler.tenant_id,
        wecom_department_id=handler.depts[0],wecom_webhook_url=SecretStr('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=fake-key-'+handler.tenant_id))
    monkeypatch.setattr(service,'get_settings',lambda:settings)
    monkeypatch.setattr(worker,'get_settings',lambda:settings)
    return settings


async def authorize(db,handler,*,enabled=True,operation='contact'):
    await service.save_contact(db,handler,handler.user_id,email='',enabled=False,wecom_enabled=enabled,operation_id=operation)
    await db.commit()


async def test_opt_in_only_department_scope_and_independent_email(oa_db,monkeypatch):
    async with oa_db() as db:
        handler,owner=await setup(db)
        settings=route(monkeypatch,handler)
        await enqueue(db,owner)
        assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom') is None
        await authorize(db,handler)
        await enqueue(db,owner)
        assert (await service.get_contact(db,handler,handler.user_id))['wecom_available']
        # An older email-only client must not revoke an existing WeCom consent.
        await service.save_contact(db,handler,handler.user_id,email='test@example.test',enabled=False,operation_id='legacy')
        await db.commit()
        assert (await service.get_contact(db,handler,handler.user_id))['wecom_enabled']
        rows=await service.list_deliveries(db,handler)
        assert sum(r['channel']=='wecom' for r in rows)==1
        assert 'fake-key' not in str(rows)
    sent=[]
    assert await worker.run_once(oa_db,tenant_id=owner.tenant_id,channel='wecom',sender=lambda claim:sent.append(claim) or 'ACCEPTED')==1
    assert len(sent)==1 and 'email' not in sent[0]['body'] and handler.user_id not in sent[0]['body']
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id) is None
    async with oa_db() as db:
        other,other_owner=await setup(db)
        await authorize(db,other)
        await enqueue(db,other_owner)
        settings.wecom_department_id='wrong-department'
        await enqueue(db,owner)
        assert await db.scalar(select(func.count()).select_from(OANotificationDelivery).where(
            OANotificationDelivery.tenant_id==other.tenant_id,OANotificationDelivery.channel=='wecom'))==0


@pytest.mark.parametrize('change',['consent','route','department','authority'])
async def test_preflight_revocation_cancels_without_io(oa_db,monkeypatch,change):
    async with oa_db() as db:
        handler,owner=await setup(db)
        settings=route(monkeypatch,handler)
        await authorize(db,handler)
        await enqueue(db,owner)
    claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom')
    assert claim
    async with oa_db() as db:
        if change=='consent': await authorize(db,handler,enabled=False,operation='revoke')
        elif change=='route': settings.wecom_webhook_url=SecretStr('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=new-group')
        elif change=='department': settings.wecom_department_id='other'
        else:
            from app.models.identity import OAUserRole
            from sqlalchemy import delete
            await db.execute(delete(OAUserRole).where(OAUserRole.tenant_id==handler.tenant_id,OAUserRole.user_id==handler.user_id))
            await db.commit()
    assert await worker.prepare_send(oa_db,claim['id'],claim['token']) is None
    async with oa_db() as db:
        row=await db.get(OANotificationDelivery,claim['id'])
        assert row.state=='CANCELLED'


async def test_unknown_requires_audited_retry_and_preserves_destination(oa_db,monkeypatch):
    async with oa_db() as db:
        handler,owner=await setup(db)
        settings=route(monkeypatch,handler)
        await authorize(db,handler)
        await enqueue(db,owner)
    claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom')
    await worker.complete(oa_db,claim['id'],claim['token'],'UNKNOWN')
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom') is None
    async with oa_db() as db:
        await service.retry_unknown(db,handler,claim['id'],note='已核对群消息，确认可能重复',operation_id='retry')
        await db.commit()
    settings.wecom_webhook_url=SecretStr('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=new-group')
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom') is None
    async with oa_db() as db:
        assert (await db.get(OANotificationDelivery,claim['id'])).state=='CANCELLED'


async def test_shared_robot_throttle_and_concurrent_claim(oa_db,monkeypatch):
    async with oa_db() as db:
        handler,owner=await setup(db)
        route(monkeypatch,handler)
        await authorize(db,handler)
        await enqueue(db,owner)
        original=await db.scalar(select(OANotificationDelivery).where(OANotificationDelivery.tenant_id==owner.tenant_id,
            OANotificationDelivery.channel=='wecom'))
        # Completed reservations from this same robot, regardless of tenant.
        for number in range(1,20):
            db.add(OANotificationAttempt(tenant_id=owner.tenant_id,delivery_id=original.id,
                number=number,token='rate-'+str(number),state='ACCEPTED',finished_at=datetime.now(timezone.utc)))
        original.attempt_count=19
        await db.commit()
    claims=await asyncio.gather(*(worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom') for _ in range(2)))
    assert sum(c is not None for c in claims)==1
    claim=next(c for c in claims if c)
    now=datetime.now(timezone.utc)
    await worker.complete(oa_db,claim['id'],claim['token'],'TEMPORARY',now=now)
    async with oa_db() as db:
        await enqueue(db,owner)
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom',now=now+timedelta(seconds=5)) is None
    async with oa_db() as db:
        pending=await db.scalar(select(OANotificationDelivery).where(OANotificationDelivery.tenant_id==owner.tenant_id,
            OANotificationDelivery.channel=='wecom',OANotificationDelivery.state=='PENDING'))
        assert pending.last_code=='wecom_rate_limited' and pending.attempt_count==0
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom',now=now+timedelta(seconds=66))


async def test_disabled_channel_does_not_invoke_sender(oa_db,monkeypatch):
    settings=Settings(_env_file=None,wecom_enabled=False)
    monkeypatch.setattr(worker,'get_settings',lambda:settings)
    assert await worker.run_once(oa_db,channel='wecom')==0


async def test_admin_cannot_grant_personal_group_consent_but_can_revoke(oa_db,monkeypatch):
    async with oa_db() as db:
        handler,owner=await setup(db)
        route(monkeypatch,handler)
        with pytest.raises(AppException) as error:
            await service.save_contact(db,handler,owner.user_id,email='',enabled=False,wecom_enabled=True,operation_id='admin-grant')
        assert error.value.http_status==403
        assert not (await service.get_contact(db,handler,owner.user_id))['wecom_enabled']
        await service.save_contact(db,owner,owner.user_id,email='',enabled=False,wecom_enabled=True,operation_id='self-grant')
        await db.commit()
        assert (await service.get_contact(db,owner,owner.user_id))['wecom_enabled']
        await service.save_contact(db,handler,owner.user_id,email='',enabled=False,wecom_enabled=False,operation_id='admin-revoke')
        await db.commit()
        assert not (await service.get_contact(db,owner,owner.user_id))['wecom_enabled']


async def test_rate_budget_is_shared_across_tenants_using_same_robot(oa_db,monkeypatch):
    async with oa_db() as db:
        first,first_owner=await setup(db)
        settings=route(monkeypatch,first)
        await authorize(db,first)
        await enqueue(db,first_owner)
        delivery=await db.scalar(select(OANotificationDelivery).where(OANotificationDelivery.tenant_id==first.tenant_id,
            OANotificationDelivery.channel=='wecom'))
        for number in range(1,20):
            db.add(OANotificationAttempt(tenant_id=first.tenant_id,delivery_id=delivery.id,number=number,
                token='shared-'+str(number),state='ACCEPTED',finished_at=datetime.now(timezone.utc)))
        delivery.state,delivery.attempt_count='ACCEPTED',19
        await db.commit()
        second,second_owner=await setup(db)
        # Simulate another worker configuration targeting another tenant but the
        # same group robot; its rate budget must still be global.
        settings.wecom_tenant_id,settings.wecom_department_id=second.tenant_id,second.depts[0]
        settings.wecom_webhook_url=SecretStr(settings.wecom_webhook_url.get_secret_value().replace('key=fake','key=%66ake'))
        await authorize(db,second)
        await enqueue(db,second_owner)
        second_delivery=await db.scalar(select(OANotificationDelivery).where(OANotificationDelivery.tenant_id==second.tenant_id,
            OANotificationDelivery.channel=='wecom'))
        assert second_delivery.destination_hash==delivery.destination_hash
        identifiers=[delivery.id,second_delivery.id]
    async def reserve(identifier):
        from uuid import uuid4
        from app.services.identity_service import lock_tenant
        async with oa_db() as db:
            row=await db.get(OANotificationDelivery,identifier)
            await lock_tenant(db,row.tenant_id)
            allowed=await worker.reserve_wecom(db,row,datetime.now(timezone.utc))
            if allowed:
                row.attempt_count+=1
                db.add(OANotificationAttempt(tenant_id=row.tenant_id,delivery_id=row.id,number=row.attempt_count,
                    token=str(uuid4()),state='PROCESSING'))
                await db.flush()
                # Keep the reservation uncommitted while the other tenant tries.
                # Without the global robot lock both would see only 19 attempts.
                await asyncio.sleep(0.2)
            await db.commit()
            return allowed
    assert sorted(await asyncio.gather(*(reserve(identifier) for identifier in identifiers)))==[False,True]
