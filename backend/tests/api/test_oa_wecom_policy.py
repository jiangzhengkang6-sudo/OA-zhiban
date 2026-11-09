"""Restricted policy tests use an isolated database and never call real robots."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from sqlalchemy import select, func
from app.core.errors import AppException
from app.models.oa_notification import OANotification, OANotificationDelivery as Delivery, OAWecomBatch as Batch, OANotificationAttempt as Attempt
from app.models.oa_workflow import OAWorkflowEvent, OAWorkflowOutbox
from app.schemas.oa_meeting import MeetingCreate, MeetingUpdate
from app.services import oa_notification_service as notifications, oa_notification_worker as worker, meeting_management_service as meetings
from tests.oa_support import oa_db, seed
from tests.api.test_oa_wecom import route, authorize
from tests.api.test_oa_notification import setup, enqueue
from tests.api.test_meeting_management import command


async def group_meeting(db, monkeypatch):
    author = await seed(db, resources=['meeting','notification'], scope='self')
    guest = await seed(db, tenant=author.tenant_id, department=author.depts[0], resources=['meeting','notification'], scope='self')
    settings = route(monkeypatch, author)
    await authorize(db, author)
    await authorize(db, guest)
    starts = datetime.now(timezone.utc) + timedelta(days=1)
    payload = MeetingCreate(operation_id=uuid4().hex, title='敏感项目评审', agenda='不得发送至群的业务正文',
        starts_at=starts, ends_at=starts+timedelta(hours=1), host_id=author.user_id, recorder_id=author.user_id,
        attendee_ids=[guest.user_id], location='机密会议室')
    row = (await meetings.save(db,author,payload)).result
    row = (await meetings.transition(db,author,row['id'],command(row),'publish')).result
    await db.commit()
    return author,guest,payload,row,settings


async def group_rows(db, tenant):
    return (await db.scalars(select(Delivery).where(Delivery.tenant_id==tenant,Delivery.channel=='wecom'))).all()


async def test_same_event_many_recipients_one_physical_receipt_and_minimal_body(oa_db,monkeypatch):
    async with oa_db() as db:
        author,guest,_,_,_=await group_meeting(db,monkeypatch)
        assert len(await group_rows(db,author.tenant_id))==2
    sent=[]
    assert await worker.run_once(oa_db,tenant_id=author.tenant_id,channel='wecom',sender=lambda c:sent.append(c) or 'ACCEPTED')==1
    assert len(sent)==1 and sent[0]['body'].startswith('有会议邀请\n')
    assert all(value not in sent[0]['body'] for value in ['敏感','机密',author.user_id,guest.user_id])
    async with oa_db() as db:
        rows=await group_rows(db,author.tenant_id)
        assert {row.state for row in rows}=={'ACCEPTED'}
        assert len({row.wecom_batch_id for row in rows})==1
        assert all(row.attempt_count==1 for row in rows)


async def test_revoked_leader_does_not_drop_other_authorized_members(oa_db,monkeypatch):
    async with oa_db() as db:
        author,guest,_,_,_=await group_meeting(db,monkeypatch)
    claim=await worker.claim_one(oa_db,tenant_id=author.tenant_id,channel='wecom')
    async with oa_db() as db:
        leader=await db.get(Delivery,claim['id'])
        notification=await db.get(OANotification,leader.notification_id)
        revoked=author if notification.recipient_id==author.user_id else guest
        await authorize(db,revoked,enabled=False,operation='revoke')
    ready=await worker.prepare_send(oa_db,claim['id'],claim['token'])
    assert ready
    assert await worker.complete(oa_db,claim['id'],claim['token'],'ACCEPTED')
    async with oa_db() as db:
        assert sorted(row.state for row in await group_rows(db,author.tenant_id))==['ACCEPTED','CANCELLED']


async def test_batch_unknown_and_expired_lease_never_automatically_repeat(oa_db,monkeypatch):
    async with oa_db() as db:
        author,_,_,_,_=await group_meeting(db,monkeypatch)
    claim=await worker.claim_one(oa_db,tenant_id=author.tenant_id,channel='wecom')
    later=datetime.now(timezone.utc)+timedelta(minutes=3)
    assert await worker.prepare_send(oa_db,claim['id'],claim['token'],now=later) is None
    assert not await worker.complete(oa_db,claim['id'],claim['token'],'ACCEPTED',now=later)
    assert await worker.claim_one(oa_db,tenant_id=author.tenant_id,channel='wecom',now=later) is None
    async with oa_db() as db:
        assert {row.state for row in await group_rows(db,author.tenant_id)}=={'UNKNOWN'}


async def test_distinct_events_are_batched_and_later_bursts_wait_for_group_interval(oa_db,monkeypatch):
    async with oa_db() as db:
        handler,owner=await setup(db)
        settings=route(monkeypatch,handler)
        settings.wecom_group_interval_seconds=60
        await authorize(db,handler)
        await enqueue(db,owner)
        await enqueue(db,owner)
    now=datetime.now(timezone.utc)
    claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom',now=now)
    assert await worker.complete(oa_db,claim['id'],claim['token'],'ACCEPTED',now=now)
    async with oa_db() as db:
        assert {row.state for row in await group_rows(db,owner.tenant_id)}=={'ACCEPTED'}
        assert await db.scalar(select(func.count()).select_from(Batch).where(Batch.tenant_id==owner.tenant_id))==1
        await enqueue(db,owner)
        await enqueue(db,owner)
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom',now=now+timedelta(seconds=5)) is None
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom',now=now+timedelta(seconds=61))


@pytest.mark.parametrize('historical',['queued','undispatched','unactivated'])
async def test_history_isolated_without_affecting_inbox_or_smtp(oa_db,monkeypatch,historical):
    async with oa_db() as db:
        handler,owner=await setup(db)
        settings=route(monkeypatch,handler)
        await authorize(db,handler)
        if historical=='undispatched':
            from tests.api.test_oa_ticket import create
            await create(db,owner,uuid4().hex)
            await db.commit()
        else: await enqueue(db,owner)
        settings.wecom_policy_activated_at=None if historical=='unactivated' else datetime.now(timezone.utc)+timedelta(seconds=1)
        await notifications.dispatch(db,tenant_id=owner.tenant_id)
        await db.commit()
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom') is None
    async with oa_db() as db:
        rows=await group_rows(db,owner.tenant_id)
        assert rows and all(row.state=='CANCELLED' and row.last_code=='wecom_history_isolated' for row in rows)
        assert (await notifications.list_inbox(db,handler))[0]['inbox_state']=='ACCEPTED'
        assert await db.scalar(select(Delivery.id).where(Delivery.tenant_id==owner.tenant_id,Delivery.channel=='smtp',Delivery.state=='PENDING'))


@pytest.mark.parametrize('change',['agenda','location','starts_at','cancel','start'])
async def test_meeting_only_invites_material_changes_and_cancellations(oa_db,monkeypatch,change):
    async with oa_db() as db:
        author,_,payload,row,_=await group_meeting(db,monkeypatch)
    first=await worker.claim_one(oa_db,tenant_id=author.tenant_id,channel='wecom')
    await worker.complete(oa_db,first['id'],first['token'],'ACCEPTED')
    async with oa_db() as db:
        if change in {'cancel','start'}:
            row=(await meetings.transition(db,author,row['id'],command(row,reason='取消安排' if change=='cancel' else ''),change)).result
        else:
            values={**payload.model_dump(),'operation_id':uuid4().hex,'expected_revision':row['revision']}
            values[change]=payload.starts_at+timedelta(hours=1) if change=='starts_at' else '变更内容'
            if change=='starts_at': values['ends_at']=payload.ends_at+timedelta(hours=1)
            row=(await meetings.save(db,author,MeetingUpdate(**values),row['id'])).result
        await db.commit()
    claim=await worker.claim_one(oa_db,tenant_id=author.tenant_id,channel='wecom')
    assert bool(claim)==(change in {'location','starts_at','cancel'})
    if claim:
        assert ('有会议取消通知' if change=='cancel' else '会议安排有变更') in claim['body']


async def test_changed_meeting_cancels_claimed_old_invite_before_io(oa_db,monkeypatch):
    async with oa_db() as db:
        author,_,_,row,_=await group_meeting(db,monkeypatch)
    first=await worker.claim_one(oa_db,tenant_id=author.tenant_id,channel='wecom')
    async with oa_db() as db:
        await meetings.transition(db,author,row['id'],command(row),'start')
        await db.commit()
    assert await worker.prepare_send(oa_db,first['id'],first['token']) is None


async def test_trusted_allowlist_ignores_client_like_source_and_denies_ticket_progress(oa_db,monkeypatch):
    from app.schemas.oa_ticket import TicketHandleCommand
    from app.services import oa_ticket_service as tickets, oa_wecom_policy as policy
    async with oa_db() as db:
        handler,owner=await setup(db)
        settings=route(monkeypatch,handler)
        await authorize(db,handler)
        ticket=await enqueue(db,owner)
        notice=await db.scalar(select(OANotification).where(OANotification.tenant_id==owner.tenant_id))
        info,_=await policy.classify(db,notice,settings)
        assert info['category']=='ticket'
        event=await db.get(OAWorkflowEvent,(await db.get(OAWorkflowOutbox,notice.source_outbox_id)).event_id)
        event.action='notification.intent'
        event.detail={**event.detail,'category':'approval'}
        notice.source={**notice.source,'category':'approval'}
        assert await policy.classify(db,notice,settings)==(None,'wecom_policy_blocked')
        await db.rollback()
        # Owner status notifications must never become external group work items.
        await authorize(db,owner)
        await tickets.handle(db,handler,ticket['id'],TicketHandleCommand(operation_id='start',expected_revision=1,action='start'))
        await notifications.dispatch(db,tenant_id=owner.tenant_id)
        await db.commit()
        blocked=await db.scalar(select(Delivery).join(OANotification,OANotification.id==Delivery.notification_id).where(
            Delivery.tenant_id==owner.tenant_id,Delivery.channel=='wecom',OANotification.recipient_id==owner.user_id))
        assert blocked.state=='CANCELLED' and blocked.last_code=='wecom_policy_blocked'


async def test_targeted_group_claim_does_not_touch_unrelated_pending_rows(oa_db,monkeypatch):
    async with oa_db() as db:
        handler,owner=await setup(db)
        route(monkeypatch,handler)
        await authorize(db,handler)
        await enqueue(db,owner)
        await enqueue(db,owner)
        rows=await group_rows(db,owner.tenant_id)
        chosen,untouched=rows
    claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom',delivery_id=chosen.id)
    assert claim['id']==chosen.id
    async with oa_db() as db:
        assert (await db.get(Delivery,untouched.id)).state=='PENDING'


async def test_temporary_batch_retry_counts_one_physical_attempt_and_stale_token_rejected(oa_db,monkeypatch):
    async with oa_db() as db:
        author,_,_,_,_=await group_meeting(db,monkeypatch)
    now=datetime.now(timezone.utc)
    claim=await worker.claim_one(oa_db,tenant_id=author.tenant_id,channel='wecom',now=now)
    assert await worker.complete(oa_db,claim['id'],claim['token'],'TEMPORARY',now=now)
    assert await worker.claim_one(oa_db,tenant_id=author.tenant_id,channel='wecom',now=now+timedelta(seconds=5)) is None
    retry=await worker.claim_one(oa_db,tenant_id=author.tenant_id,channel='wecom',now=now+timedelta(seconds=65))
    assert retry and not await worker.complete(oa_db,claim['id'],claim['token'],'ACCEPTED',now=now+timedelta(seconds=65))
    assert await worker.complete(oa_db,retry['id'],retry['token'],'ACCEPTED',now=now+timedelta(seconds=65))
    async with oa_db() as db:
        assert await db.scalar(select(func.count()).select_from(Batch).where(Batch.tenant_id==author.tenant_id))==2
        assert await db.scalar(select(func.count()).select_from(Attempt).where(Attempt.tenant_id==author.tenant_id))==4


async def grant_notifications(db,actor):
    from app.models.identity import OAPermission, OAUserRole, OARolePermission
    role=await db.scalar(select(OAUserRole.role_id).where(OAUserRole.tenant_id==actor.tenant_id,OAUserRole.user_id==actor.user_id))
    for action in ('read','write'):
        permission=await db.scalar(select(OAPermission).where(OAPermission.resource=='notification',OAPermission.action==action,OAPermission.scope=='self'))
        if not permission:
            permission=OAPermission(resource='notification',action=action,scope='self')
            db.add(permission)
            await db.flush()
        db.add(OARolePermission(tenant_id=actor.tenant_id,role_id=role,permission_id=permission.id))
    await db.commit()


async def test_ticket_reassignment_only_notifies_current_handler_and_reopen_is_allowed(oa_db,monkeypatch):
    from app.schemas.oa_ticket import TicketHandleCommand, TicketFeedbackCommand
    from app.services import oa_ticket_service as tickets
    async with oa_db() as db:
        handler,owner=await setup(db)
        replacement=await seed(db,tenant=owner.tenant_id,department=owner.depts[0],
            resources=['ticket_handle','notification'],scope='department')
        route(monkeypatch,handler)
        for actor in (handler,owner,replacement): await authorize(db,actor)
        ticket=await enqueue(db,owner)
        await tickets.handle(db,handler,ticket['id'],TicketHandleCommand(operation_id='move',
            expected_revision=1,action='reassign',target_user_id=replacement.user_id,note='转交处理'))
        await notifications.dispatch(db,tenant_id=owner.tenant_id)
        await db.commit()
    claim=await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom')
    assert claim and claim['body'].startswith('有工单待处理\n')
    await worker.complete(oa_db,claim['id'],claim['token'],'ACCEPTED')
    async with oa_db() as db:
        rows=(await db.execute(select(Delivery,OANotification.recipient_id).join(OANotification,
            OANotification.id==Delivery.notification_id).where(Delivery.tenant_id==owner.tenant_id,
                Delivery.channel=='wecom'))).all()
        assert {recipient for row,recipient in rows if row.state=='ACCEPTED'}=={replacement.user_id}
        await tickets.handle(db,replacement,ticket['id'],TicketHandleCommand(operation_id='resolve',
            expected_revision=2,action='resolve',note='已完成处理'))
        await notifications.dispatch(db,tenant_id=owner.tenant_id)
        await db.commit()
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom') is None
    async with oa_db() as db:
        await tickets.feedback(db,owner,ticket['id'],TicketFeedbackCommand(operation_id='reopen',
            expected_revision=3,resolved=False,comment='问题仍存在'))
        await notifications.dispatch(db,tenant_id=owner.tenant_id)
        await db.commit()
    assert await worker.claim_one(oa_db,tenant_id=owner.tenant_id,channel='wecom')


async def test_approval_allowlist_and_two_hour_nudge_cooldown(oa_db,monkeypatch):
    from tests.api.test_oa_approval_modes import submitted
    from app.models.oa_workflow import OAWorkflowNode
    from app.services import oa_workflow_scheduler as timers, oa_wecom_policy as policy
    async with oa_db() as db:
        approver,_,_,_,_=await submitted(db)
        settings=route(monkeypatch,approver)
        await grant_notifications(db,approver)
        await authorize(db,approver)
        await notifications.dispatch(db,tenant_id=approver.tenant_id)
        await db.commit()
        first_notice=await db.scalar(select(OANotification).where(OANotification.tenant_id==approver.tenant_id,
            OANotification.recipient_id==approver.user_id,OANotification.source['resource'].as_string()=='approval'))
        assert (await policy.classify(db,first_notice,settings))[0]['category']=='approval'
        node=await db.scalar(select(OAWorkflowNode).where(OAWorkflowNode.tenant_id==approver.tenant_id))
        now=datetime.now(timezone.utc)
        node.due_at=now+timedelta(minutes=1)
        await db.commit()
        assert (await timers.scan(db,actor=approver,now=now))['processed']==1
        await notifications.dispatch(db,tenant_id=approver.tenant_id)
        await db.commit()
    claim=await worker.claim_one(oa_db,tenant_id=approver.tenant_id,channel='wecom',now=now)
    assert '有审批催办事项' in claim['body'] and '有待审批事项' in claim['body']
    await worker.complete(oa_db,claim['id'],claim['token'],'ACCEPTED',now=now)
    async def another_nudge():
        async with oa_db() as db:
            event=await db.scalar(select(OAWorkflowEvent).where(OAWorkflowEvent.tenant_id==approver.tenant_id,OAWorkflowEvent.action=='workflow.nudge'))
            clone=OAWorkflowEvent(tenant_id=approver.tenant_id,operation_id=event.operation_id,actor_id=event.actor_id,
                action=event.action,target_id=event.target_id,event_key=uuid4().hex,detail=event.detail)
            db.add(clone)
            await db.flush()
            db.add(OAWorkflowOutbox(tenant_id=approver.tenant_id,event_id=clone.id,recipient_id=approver.user_id,payload={}))
            await db.flush()
            await notifications.dispatch(db,tenant_id=approver.tenant_id)
            await db.commit()
    await another_nudge()
    assert await worker.claim_one(oa_db,tenant_id=approver.tenant_id,channel='wecom',now=now+timedelta(hours=1)) is None
    async with oa_db() as db:
        assert any(row.last_code=='wecom_nudge_cooldown' for row in await group_rows(db,approver.tenant_id))
    await another_nudge()
    assert await worker.claim_one(oa_db,tenant_id=approver.tenant_id,channel='wecom',now=now+timedelta(hours=2,seconds=1))


async def test_late_recipient_of_already_sent_event_is_merged_not_resent(oa_db,monkeypatch):
    async with oa_db() as db:
        author,_,_,_,_=await group_meeting(db,monkeypatch)
        chosen=(await group_rows(db,author.tenant_id))[0]
    first=await worker.claim_one(oa_db,tenant_id=author.tenant_id,channel='wecom',delivery_id=chosen.id)
    await worker.complete(oa_db,first['id'],first['token'],'ACCEPTED')
    assert await worker.claim_one(oa_db,tenant_id=author.tenant_id,channel='wecom') is None
    async with oa_db() as db:
        rows=await group_rows(db,author.tenant_id)
        assert sorted(row.state for row in rows)==['ACCEPTED','CANCELLED']
        assert any(row.last_code=='wecom_event_merged' for row in rows)
        assert len({row.wecom_batch_id for row in rows})==1


async def test_controlled_probe_is_self_only_idempotent_and_cleans_up_without_second_send(oa_db,monkeypatch):
    from argparse import Namespace
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.models.identity import OAUser
    from app.models.oa_meeting import OAMeeting
    from scripts import verify_restricted_wecom as probe
    async with oa_db() as db:
        author,_,_,_,settings=await group_meeting(db,monkeypatch)
        settings.auth_tenant_id=author.tenant_id
        user=await db.get(OAUser,author.user_id)
        options=Namespace(send=True,isolate_history=False,username=user.normalized_username,run_id=uuid4().hex)
    monkeypatch.setattr(probe,'async_session_factory',oa_db)
    monkeypatch.setattr(probe,'engine',SimpleNamespace(dispose=AsyncMock()))
    monkeypatch.setattr(probe,'get_settings',lambda:settings)
    sent=[]
    monkeypatch.setattr(probe.wecom,'send',lambda claim:sent.append(claim) or 'ACCEPTED')
    receipt=await probe.run(options)
    assert receipt['state']=='ACCEPTED' and receipt['smtp_sent'] is False
    assert receipt['attempt_count']==1 and receipt['member_confirmation']=='UNVERIFIED'
    again=await probe.run(options)
    assert again['delivery_id']==receipt['delivery_id'] and len(sent)==1
    async with oa_db() as db:
        assert await db.scalar(select(OAMeeting.id).where(OAMeeting.tenant_id==author.tenant_id,
            OAMeeting.state=='CANCELLED'))
        rows=await group_rows(db,author.tenant_id)
        assert sum(row.last_code=='wecom_probe_cleanup' for row in rows)==1
        assert sum(row.state=='PENDING' for row in rows)==2  # Unrelated invitation is untouched.
        assert await db.scalar(select(func.count()).select_from(Delivery).where(Delivery.tenant_id==author.tenant_id,
            Delivery.channel=='smtp',Delivery.last_code=='notification_probe_cleanup'))==2
