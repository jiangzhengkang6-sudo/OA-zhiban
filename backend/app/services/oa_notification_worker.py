"""Claim/commit before external IO; finish only the current attempt token."""
import asyncio
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from sqlalchemy import select,or_,func,text
from ..core.config import get_settings
from ..models.oa_notification import OANotification,OANotificationDelivery,OANotificationAttempt,OAUserContact
from .identity_service import lock_tenant
from . import oa_notification_source as sources
from .oa_access_service import user_department
from ..providers.wecom import destination


async def resolve_contact(db,row,notification):
    contact=await db.scalar(select(OAUserContact).where(OAUserContact.tenant_id==row.tenant_id,
        OAUserContact.user_id==notification.recipient_id))
    if row.channel=='smtp':
        return contact.email if contact and contact.enabled else None
    if row.channel!='wecom' or not contact or not contact.wecom_enabled:
        return None
    current=await user_department(db,row.tenant_id,notification.recipient_id)
    fingerprint=destination(get_settings(),row.tenant_id,current)
    if current!=notification.department_id or not fingerprint or fingerprint!=row.destination_hash:
        return None
    return 'wecom-group'


def payload(row,notification,recipient):
    return dict(id=row.id,token=row.attempt_token,recipient=recipient,message_id=row.message_id,
        tenant_id=row.tenant_id,department_id=notification.department_id,destination_hash=row.destination_hash,
        body='您有新的 OA 业务提醒，请登录系统查看。\n'+get_settings().notification_app_url)


async def reserve_wecom(db,row,now):
    # Serialize reservations across processes sharing a robot. In-flight requests
    # stay in the window until finished, including slow/ambiguous network calls.
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
        {'key':'oa-wecom:'+row.destination_hash})
    count=await db.scalar(select(func.count()).select_from(OANotificationAttempt)
        .join(OANotificationDelivery,OANotificationAttempt.delivery_id==OANotificationDelivery.id)
        .where(OANotificationDelivery.channel=='wecom',OANotificationDelivery.destination_hash==row.destination_hash,
            or_(OANotificationAttempt.finished_at.is_(None),OANotificationAttempt.finished_at>=now-timedelta(seconds=60))))
    if count>=20:
        row.last_code='wecom_rate_limited'
        row.next_attempt_at=now+timedelta(seconds=60)
        return False
    return True


async def expire(db,tenant,now):
    rows=(await db.scalars(select(OANotificationDelivery).where(OANotificationDelivery.tenant_id==tenant,
        OANotificationDelivery.state=='PROCESSING',OANotificationDelivery.lease_until<=now).with_for_update(skip_locked=True))).all()
    for row in rows:
        row.state,row.last_code='UNKNOWN','lease_expired_possible_acceptance'
        attempt=await db.scalar(select(OANotificationAttempt).where(OANotificationAttempt.tenant_id==tenant,
            OANotificationAttempt.token==row.attempt_token))
        if attempt: attempt.state,attempt.finished_at='UNKNOWN',now


async def claim_one(factory,*,tenant_id=None,now=None,channel='smtp'):
    if channel not in {'smtp','wecom'}: raise ValueError('Unsupported notification channel')
    now=now or datetime.now(timezone.utc)
    async with factory() as db:
        query=select(OANotificationDelivery.tenant_id).where(OANotificationDelivery.channel==channel,
            OANotificationDelivery.state.in_(['PENDING','PROCESSING']))
        if tenant_id: query=query.where(OANotificationDelivery.tenant_id==tenant_id)
        tenants=(await db.scalars(query.distinct().order_by(OANotificationDelivery.tenant_id))).all()
        for tenant in tenants:
            await lock_tenant(db,tenant)
            await expire(db,tenant,now)
            rows=(await db.scalars(select(OANotificationDelivery).where(OANotificationDelivery.tenant_id==tenant,
                OANotificationDelivery.channel==channel,OANotificationDelivery.state=='PENDING',
                or_(OANotificationDelivery.next_attempt_at.is_(None),OANotificationDelivery.next_attempt_at<=now))
                # Scan every due row for this tenant. Unconfigured recipients remain
                # pending, so a fixed page could otherwise starve a later configured
                # delivery indefinitely.
                .order_by(OANotificationDelivery.created_at,OANotificationDelivery.id).with_for_update(skip_locked=True))).all()
            for row in rows:
                notification=await db.get(OANotification,row.notification_id)
                if not await sources.allowed(db,notification):
                    row.state,row.last_code='CANCELLED','source_unavailable'
                    continue
                recipient=await resolve_contact(db,row,notification)
                if not recipient:
                    if channel=='wecom': row.state='CANCELLED'
                    row.last_code='destination_or_consent_unavailable' if channel=='wecom' else 'contact_not_configured'
                    continue
                if channel=='wecom' and not await reserve_wecom(db,row,now): continue
                row.attempt_count+=1
                row.state,row.attempt_token,row.lease_until='PROCESSING',str(uuid4()),now+timedelta(minutes=2)
                db.add(OANotificationAttempt(tenant_id=tenant,delivery_id=row.id,number=row.attempt_count,
                    token=row.attempt_token,state='PROCESSING'))
                claim=payload(row,notification,recipient)
                await db.commit()
                return claim
            await db.commit()
    return None


async def complete(factory,delivery_id,token,outcome,*,now=None):
    now=now or datetime.now(timezone.utc)
    if outcome not in {'ACCEPTED','TEMPORARY','PERMANENT','UNKNOWN'}: outcome='UNKNOWN'
    async with factory() as db:
        initial=await db.get(OANotificationDelivery,delivery_id)
        if not initial: return False
        await lock_tenant(db,initial.tenant_id)
        row=await db.scalar(select(OANotificationDelivery).where(OANotificationDelivery.id==delivery_id)
            .with_for_update().execution_options(populate_existing=True))
        if row.state!='PROCESSING' or row.attempt_token!=token: return False
        if row.lease_until<=now: outcome='UNKNOWN'
        attempt=await db.scalar(select(OANotificationAttempt).where(OANotificationAttempt.tenant_id==row.tenant_id,
            OANotificationAttempt.token==token))
        attempt.state,attempt.finished_at=outcome,now
        row.state=outcome if outcome in {'ACCEPTED','UNKNOWN'} else 'FAILED'
        if outcome=='TEMPORARY' and row.attempt_count<=3:
            row.state='PENDING'
            row.next_attempt_at=now+timedelta(minutes=(1,5,30)[row.attempt_count-1])
        row.last_code=row.channel+'_'+outcome.lower()
        row.lease_until=None
        await db.commit()
        return True


async def recover(factory,*,tenant_id=None,now=None,channel='smtp'):
    now=now or datetime.now(timezone.utc)
    async with factory() as db:
        query=select(OANotificationDelivery.tenant_id).where(OANotificationDelivery.channel==channel,
            OANotificationDelivery.state=='PROCESSING',OANotificationDelivery.lease_until<=now)
        if tenant_id: query=query.where(OANotificationDelivery.tenant_id==tenant_id)
        for tenant in (await db.scalars(query.distinct().order_by(OANotificationDelivery.tenant_id))).all():
            await lock_tenant(db,tenant)
            await expire(db,tenant,now)
        await db.commit()


async def prepare_send(factory,delivery_id,token,*,now=None):
    """Resolve current authority/address after claim commit, immediately before IO."""
    now=now or datetime.now(timezone.utc)
    async with factory() as db:
        initial=await db.get(OANotificationDelivery,delivery_id)
        if not initial: return None
        await lock_tenant(db,initial.tenant_id)
        row=await db.scalar(select(OANotificationDelivery).where(OANotificationDelivery.id==delivery_id)
            .with_for_update().execution_options(populate_existing=True))
        if row.state!='PROCESSING' or row.attempt_token!=token: return None
        if row.lease_until<=now:
            await expire(db,row.tenant_id,now)
            await db.commit()
            return None
        notification=await db.get(OANotification,row.notification_id)
        permitted=await sources.allowed(db,notification)
        recipient=await resolve_contact(db,row,notification) if permitted else None
        if not recipient:
            row.state,row.last_code,row.lease_until='CANCELLED','preflight_unavailable',None
            attempt=await db.scalar(select(OANotificationAttempt).where(OANotificationAttempt.tenant_id==row.tenant_id,
                OANotificationAttempt.token==token))
            attempt.state,attempt.finished_at='PERMANENT',now
            await db.commit()
            return None
        claim=payload(row,notification,recipient)
        await db.commit()
        return claim


async def run_once(factory,*,tenant_id=None,sender=None,limit=50,channel='smtp'):
    if channel not in {'smtp','wecom'}: raise ValueError('Unsupported notification channel')
    await recover(factory,tenant_id=tenant_id,channel=channel)
    if sender is None:
        if channel=='wecom':
            settings=get_settings()
            if not destination(settings,settings.wecom_tenant_id,settings.wecom_department_id): return 0
            from ..providers.wecom import send
        else:
            if not get_settings().smtp_enabled: return 0
            from ..providers.smtp import send
        sender=send
    processed=0
    for _ in range(limit):
        claim=await claim_one(factory,tenant_id=tenant_id,channel=channel)
        if not claim: break
        claim=await prepare_send(factory,claim['id'],claim['token'])
        if not claim: continue
        try: outcome=await asyncio.to_thread(sender,claim)
        except Exception: outcome='UNKNOWN'
        await complete(factory,claim['id'],claim['token'],outcome)
        processed+=1
    return processed
