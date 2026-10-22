"""Persistent inbox and explicit private contact/unknown-result management."""
from datetime import datetime,timezone
import re
from uuid import uuid4
from sqlalchemy import select
from ..core.config import get_settings
from ..providers.wecom import destination
from ..models.identity import OAUser
from ..models.oa_workflow import OAWorkflowOutbox,OAWorkflowEvent,OAWorkflowOperation
from ..models.oa_notification import OAUserContact,OANotification,OANotificationDelivery
from .oa_access_service import builtin_actor,authorize_oa,OAAccessTarget,user_department,tenant_row,invalid,denied
from .oa_command_service import OACommand,CommandOutcome,run_command,canonical_hash
from .identity_service import lock_tenant
from . import oa_notification_source as sources


async def dispatch(db,*,tenant_id=None,limit=100):
    query=select(OAWorkflowOutbox.tenant_id).where(OAWorkflowOutbox.status=='PENDING')
    if tenant_id: query=query.where(OAWorkflowOutbox.tenant_id==tenant_id)
    tenants=(await db.scalars(query.distinct().order_by(OAWorkflowOutbox.tenant_id))).all()
    count=0
    for tenant in tenants:
        await lock_tenant(db,tenant)
        rows=(await db.scalars(select(OAWorkflowOutbox).where(OAWorkflowOutbox.tenant_id==tenant,
            OAWorkflowOutbox.status=='PENDING').order_by(OAWorkflowOutbox.created_at,OAWorkflowOutbox.id)
            .limit(max(0,limit-count)).with_for_update(skip_locked=True))).all()
        for row in rows:
            exists=await db.scalar(select(OANotification).where(OANotification.tenant_id==tenant,OANotification.source_outbox_id==row.id,
                OANotification.recipient_id==row.recipient_id))
            if not exists:
                event=await db.get(OAWorkflowEvent,row.event_id)
                notification=OANotification(id=str(uuid4()),tenant_id=tenant,source_outbox_id=row.id,recipient_id=row.recipient_id,
                    department_id=await user_department(db,tenant,row.recipient_id),source=await sources.describe(db,event,row.recipient_id))
                db.add(notification)
                await db.flush()
                permitted=await sources.allowed(db,notification)
                for channel in ('inbox','smtp'):
                    db.add(OANotificationDelivery(tenant_id=tenant,notification_id=notification.id,channel=channel,
                        state=('ACCEPTED' if channel=='inbox' else 'PENDING') if permitted else 'CANCELLED',
                        message_id='<oa-'+notification.id+'@notification.invalid>',attempt_count=0))
                contact=await db.scalar(select(OAUserContact).where(OAUserContact.tenant_id==tenant,
                    OAUserContact.user_id==notification.recipient_id))
                fingerprint=destination(get_settings(),tenant,notification.department_id)
                if permitted and fingerprint and contact and contact.wecom_enabled:
                    db.add(OANotificationDelivery(tenant_id=tenant,notification_id=notification.id,channel='wecom',
                        state='PENDING',destination_hash=fingerprint,
                        message_id='<oa-'+notification.id+'@notification.invalid>',attempt_count=0))
            row.status='SENT'
            count+=1
        if count>=limit: break
    await db.flush()
    return count


async def inbox_actor(db,actor,action='read'):
    actor=await builtin_actor(db,actor)
    await authorize_oa(db,actor,'notification',action,target=OAAccessTarget(actor.tenant_id,actor.user_id,
        await user_department(db,actor.tenant_id,actor.user_id)))
    return actor


async def item_view(db,row):
    deliveries=(await db.scalars(select(OANotificationDelivery).where(OANotificationDelivery.tenant_id==row.tenant_id,
        OANotificationDelivery.notification_id==row.id))).all()
    states={item.channel:item.state for item in deliveries}
    source=row.source
    return dict(id=row.id,title='有新的业务处理提醒',created_at=row.created_at.isoformat(),
        read_at=row.read_at.isoformat() if row.read_at else None,source_kind=source.get('kind'),
        object_id=source.get('object_id'),instance_id=source.get('instance_id'),resource=source.get('resource'),
        inbox_state=states.get('inbox'),smtp_state=states.get('smtp'),wecom_state=states.get('wecom'),
        delivered=states.get('inbox')=='ACCEPTED')


async def list_inbox(db,actor):
    actor=await inbox_actor(db,actor)
    rows=(await db.scalars(select(OANotification).where(OANotification.tenant_id==actor.tenant_id,
        OANotification.recipient_id==actor.user_id).order_by(OANotification.created_at.desc()))).all()
    result=[]
    for row in rows:
        if await sources.allowed(db,row):
            item=await item_view(db,row)
            if item['inbox_state']=='ACCEPTED': result.append(item)
    return result


async def mark_read(db,actor,notification_id):
    actor=await inbox_actor(db,actor,'write')
    await lock_tenant(db,actor.tenant_id)
    async def access():
        row=await tenant_row(db,OANotification,actor,notification_id,lock=True)
        if row.recipient_id!=actor.user_id or not await sources.allowed(db,row): raise denied()
        return row
    row=await access()
    target=OAAccessTarget(actor.tenant_id,actor.user_id,await user_department(db,actor.tenant_id,actor.user_id))
    async def perform(operation):
        row=await access()
        row.read_at=row.read_at or datetime.now(timezone.utc)
        await db.flush()
        return CommandOutcome(result=dict(id=row.id,read_at=row.read_at.isoformat()),detail=dict(notification_id=row.id))
    await run_command(db,actor,OACommand(kind='notification.read',target_id=row.id,target_version='read',
        operation_id='read:'+row.id,payload=dict(notification_id=row.id),resource='notification',target=target,
        reauthorize=access),perform)
    return await item_view(db,row)


async def contact_access(db,actor,user_id,action):
    actor=await builtin_actor(db,actor)
    user=await tenant_row(db,OAUser,actor,user_id)
    if user.status!='active': raise invalid('收件账号未启用')
    target=OAAccessTarget(actor.tenant_id,user_id,await user_department(db,actor.tenant_id,user_id))
    resource='notification' if user_id==actor.user_id else 'notification_admin'
    await authorize_oa(db,actor,resource,action,target=target)
    return actor,resource,target


async def get_contact(db,actor,user_id):
    actor,_,_=await contact_access(db,actor,user_id,'read')
    row=await db.scalar(select(OAUserContact).where(OAUserContact.tenant_id==actor.tenant_id,OAUserContact.user_id==user_id))
    department=await user_department(db,actor.tenant_id,user_id)
    return dict(user_id=user_id,email=row.email if row else '',enabled=row.enabled if row else False,
        wecom_enabled=row.wecom_enabled if row else False,
        wecom_available=bool(destination(get_settings(),actor.tenant_id,department)))


async def save_contact(db,actor,user_id,*,email,enabled,operation_id,wecom_enabled=None):
    if not isinstance(email,str) or len(email)>254 or ((email or enabled) and not re.fullmatch(r'[^\s@<>\x00-\x1f\x7f]+@[^\s@<>\x00-\x1f\x7f]+\.[^\s@<>\x00-\x1f\x7f]+',email)):
        raise invalid('请输入有效邮箱地址')
    actor,resource,target=await contact_access(db,actor,user_id,'write')
    if wecom_enabled is True and actor.user_id!=user_id: raise denied()
    async def perform(operation):
        await contact_access(db,actor,user_id,'write')
        if wecom_enabled is True and actor.user_id!=user_id: raise denied()
        row=await db.scalar(select(OAUserContact).where(OAUserContact.tenant_id==actor.tenant_id,OAUserContact.user_id==user_id))
        if row is None:
            row=OAUserContact(tenant_id=actor.tenant_id,user_id=user_id,email=email,enabled=enabled)
            db.add(row)
        else: row.email,row.enabled=email,enabled
        if wecom_enabled is not None: row.wecom_enabled=wecom_enabled
        await db.flush()
        return CommandOutcome(result=dict(user_id=user_id,enabled=enabled,wecom_enabled=row.wecom_enabled),
            detail=dict(user_id=user_id,enabled=enabled,wecom_enabled=row.wecom_enabled,contact_changed=True))
    payload=dict(email_hash=canonical_hash(email),enabled=enabled)
    if wecom_enabled is not None: payload['wecom_enabled']=wecom_enabled
    return await run_command(db,actor,OACommand(kind='notification.contact',target_id=user_id,target_version='contact',operation_id=operation_id,
        payload=payload,resource=resource,target=target),perform)


async def management_target(db,actor,notification,action):
    current=await user_department(db,actor.tenant_id,notification.recipient_id)
    if current!=notification.department_id: raise denied()
    target=OAAccessTarget(actor.tenant_id,notification.recipient_id,current)
    await authorize_oa(db,actor,'notification_admin',action,target=target)
    return target


async def list_deliveries(db,actor):
    actor=await builtin_actor(db,actor)
    from .authorization_service import require_permission
    require_permission(actor,'notification_admin','read')
    rows=(await db.scalars(select(OANotificationDelivery).where(OANotificationDelivery.tenant_id==actor.tenant_id,
        OANotificationDelivery.channel.in_(['smtp','wecom'])).order_by(OANotificationDelivery.created_at.desc()))).all()
    result=[]
    from ..core.errors import AppException
    for row in rows:
        notification=await db.get(OANotification,row.notification_id)
        try: await management_target(db,actor,notification,'read')
        except AppException: continue
        reviews=(await db.scalars(select(OAWorkflowOperation).where(OAWorkflowOperation.tenant_id==actor.tenant_id,
            OAWorkflowOperation.kind=='notification.retry',OAWorkflowOperation.target_id==row.id)
            .order_by(OAWorkflowOperation.created_at))).all()
        result.append(dict(id=row.id,notification_id=row.notification_id,recipient_id=notification.recipient_id,channel=row.channel,state=row.state,
            attempt_count=row.attempt_count,last_code=row.last_code,next_attempt_at=row.next_attempt_at.isoformat() if row.next_attempt_at else None,
            reviews=[dict(note=review.result.get('review_note',''),reviewer_id=review.actor_id,created_at=review.created_at.isoformat()) for review in reviews]))
    return result


async def retry_unknown(db,actor,delivery_id,*,note,operation_id):
    actor=await builtin_actor(db,actor)
    row=await tenant_row(db,OANotificationDelivery,actor,delivery_id)
    notification=await tenant_row(db,OANotification,actor,row.notification_id)
    target=await management_target(db,actor,notification,'write')
    if not note or not note.strip() or len(note)>1000: raise invalid('请填写人工核对备注')
    async def perform(operation):
        current=await tenant_row(db,OANotificationDelivery,actor,delivery_id,lock=True)
        await management_target(db,actor,notification,'write')
        if current.channel not in {'smtp','wecom'} or current.state!='UNKNOWN': raise invalid('仅可核对并重试结果不明的通知')
        if not await sources.allowed(db,notification): raise invalid('通知来源或收件人已失效')
        current.state,current.next_attempt_at,current.attempt_token,current.lease_until='PENDING',None,None,None
        current.last_code='manual_retry_possible_duplicate'
        await db.flush()
        return CommandOutcome(result=dict(id=current.id,state=current.state,review_note=note),detail=dict(delivery_id=current.id,
            review_note_hash=canonical_hash(note),possible_duplicate=True))
    return await run_command(db,actor,OACommand(kind='notification.retry',target_id=row.id,target_version='review',operation_id=operation_id,
        payload=dict(delivery_id=row.id,note_hash=canonical_hash(note)),resource='notification_admin',target=target),perform)
