"""Restricted, one-member business probe. No SMTP sends and no queue draining."""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, func, text
from app.core.config import get_settings
from app.db.session import async_session_factory, engine
from app.models.identity import OAUser
from app.models.oa_notification import OAUserContact, OANotification, OANotificationDelivery as Delivery
from app.models.oa_workflow import OAWorkflowOutbox, OAWorkflowEvent
from app.schemas.oa_meeting import MeetingCreate, MeetingCommand
from app.services import meeting_management_service as meetings, oa_notification_worker as worker
from app.services.identity_service import current_identity, lock_tenant
from app.providers import wecom


async def run(options):
    settings=get_settings()
    try:
        async with async_session_factory() as db:
            if not options.send and not options.isolate_history:
                await db.execute(text('SET TRANSACTION READ ONLY'))
            version=await db.scalar(text('SELECT version_num FROM alembic_version'))
            user=await db.scalar(select(OAUser).where(OAUser.tenant_id==settings.auth_tenant_id,
                OAUser.normalized_username==options.username,OAUser.status=='active'))
            if not user: raise ValueError('active_member_required')
            actor=await current_identity(db,user)
            contact=await db.scalar(select(OAUserContact).where(OAUserContact.tenant_id==actor.tenant_id,OAUserContact.user_id==actor.user_id))
            ready=bool(contact and contact.wecom_enabled and actor.depts and wecom.destination(settings,actor.tenant_id,actor.depts[0]))
            if not options.send and not options.isolate_history:
                return dict(schema=version,recipient_authorized=ready,cutover_set=settings.wecom_policy_activated_at is not None,
                    wecom_worker=settings.notification_wecom_worker_enabled,smtp_worker=settings.notification_smtp_worker_enabled,
                    business_scheduler=settings.business_scheduler_enabled,
                    pending_wecom=await db.scalar(select(func.count()).select_from(Delivery).where(Delivery.channel=='wecom',Delivery.state=='PENDING')))
            if version!='0037' or settings.wecom_policy_activated_at is None: raise ValueError('migration_and_cutover_required')
            if settings.notification_wecom_worker_enabled: raise ValueError('pause_automatic_wecom_worker_for_probe')
            if options.isolate_history:
                await lock_tenant(db,actor.tenant_id)
                rows=(await db.scalars(select(Delivery).join(OANotification,OANotification.id==Delivery.notification_id)
                    .join(OAWorkflowOutbox,OAWorkflowOutbox.id==OANotification.source_outbox_id)
                    .join(OAWorkflowEvent,OAWorkflowEvent.id==OAWorkflowOutbox.event_id).where(
                        Delivery.tenant_id==actor.tenant_id,Delivery.channel=='wecom',Delivery.state=='PENDING',
                        OAWorkflowEvent.created_at<settings.wecom_policy_activated_at).with_for_update())).all()
                for row in rows: row.state,row.last_code='CANCELLED','wecom_history_isolated'
                await db.commit()
                return dict(isolated_history=len(rows),smtp_untouched=True)
            if not ready: raise ValueError('existing_self_consent_and_department_route_required')
            starts=datetime.now(timezone.utc)+timedelta(days=1)
            payload=MeetingCreate(operation_id=options.run_id+'-create',title='[验收] 企业微信白名单验证，无需参会',
                agenda='单条受控群通知验证，不是实际会议。',starts_at=starts,ends_at=starts+timedelta(minutes=15),
                host_id=actor.user_id,recorder_id=actor.user_id,attendee_ids=[actor.user_id],location='仅验证通知链路')
            # A stable run id must reuse the original fields after interruption.
            from app.models.oa_workflow import OAWorkflowOperation
            previous=await db.scalar(select(OAWorkflowOperation).where(OAWorkflowOperation.tenant_id==actor.tenant_id,
                OAWorkflowOperation.actor_id==actor.user_id,OAWorkflowOperation.kind=='meeting.save',
                OAWorkflowOperation.operation_id==options.run_id+'-create'))
            if previous:
                row=await meetings.detail(db,actor,previous.target_id)
            else: row=(await meetings.save(db,actor,payload)).result
            if row['state']=='DRAFT':
                row=(await meetings.transition(db,actor,row['id'],MeetingCommand(operation_id=options.run_id+'-publish',expected_revision=row['revision']),'publish')).result
            delivery=await db.scalar(select(Delivery).join(OANotification,OANotification.id==Delivery.notification_id)
                .join(OAWorkflowOutbox,OAWorkflowOutbox.id==OANotification.source_outbox_id)
                .join(OAWorkflowEvent,OAWorkflowEvent.id==OAWorkflowOutbox.event_id).where(
                    Delivery.tenant_id==actor.tenant_id,Delivery.channel=='wecom',OANotification.recipient_id==actor.user_id,
                    OAWorkflowEvent.target_id==row['id'],OAWorkflowEvent.action=='meeting.publish'))
            if not delivery: raise ValueError('single_probe_delivery_missing')
            delivery_id=delivery.id
            await db.commit()
        claim=await worker.claim_one(async_session_factory,tenant_id=actor.tenant_id,channel='wecom',delivery_id=delivery_id)
        if claim:
            claim=await worker.prepare_send(async_session_factory,claim['id'],claim['token'])
            if claim:
                try: outcome=await asyncio.to_thread(wecom.send,claim)
                except Exception: outcome='UNKNOWN'
                await worker.complete(async_session_factory,claim['id'],claim['token'],outcome)
        async with async_session_factory() as db:
            receipt=await db.get(Delivery,delivery_id)
            report=dict(state=receipt.state,attempt_count=receipt.attempt_count,batch_id=receipt.wecom_batch_id,
                delivery_id=receipt.id,smtp_sent=False,member_confirmation='UNVERIFIED')
            if receipt.state in {'ACCEPTED','UNKNOWN','FAILED','CANCELLED'}:
                current=await meetings.detail(db,actor,row['id'])
                if current['state']=='SCHEDULED':
                    await meetings.transition(db,actor,row['id'],MeetingCommand(operation_id=options.run_id+'-cleanup',
                        expected_revision=current['revision'],reason='受控通知验收已结束，无实际会议'),'cancel')
                cancellations=(await db.scalars(select(Delivery).join(OANotification,OANotification.id==Delivery.notification_id).where(
                    Delivery.tenant_id==actor.tenant_id,Delivery.channel.in_(['wecom','smtp']),Delivery.state=='PENDING',
                    OANotification.source['object_id'].as_string()==row['id']))).all()
                for item in cancellations:
                    item.state='CANCELLED'
                    item.last_code='wecom_probe_cleanup' if item.channel=='wecom' else 'notification_probe_cleanup'
                await db.commit()
            return report
    finally:
        await engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--send',action='store_true')
    group.add_argument('--isolate-history',action='store_true')
    parser.add_argument('--username',default='oa_admin')
    parser.add_argument('--run-id',default='wecom-policy-20261026')
    options=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',options.run_id): parser.error('safe stable run id required')
    try: report=asyncio.run(run(options))
    except Exception as error:
        print(json.dumps(dict(error='restricted_probe_incomplete',error_type=type(error).__name__)))
        return 1
    print(json.dumps(report,ensure_ascii=True,indent=2))
    return 1 if options.send and report.get('state')!='ACCEPTED' else 0


if __name__=='__main__': sys.exit(main())
