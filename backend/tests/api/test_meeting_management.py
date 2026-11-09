from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.core.errors import AppException
from app.models.oa_notification import OANotification
from app.models.identity import OAUser, OAPermission, OARolePermission, OAUserRole
from app.models.oa_meeting import OAMeeting
from app.schemas.oa_meeting import MeetingCreate, MeetingUpdate, MeetingCommand, MeetingReply
from app.services import meeting_management_service as service
from app.services.identity_service import utcnow
from tests.oa_support import oa_db, seed


def command(row, **extra):
    return MeetingCommand(operation_id=str(uuid4()), expected_revision=row['revision'], **extra)


async def setup(db):
    author = await seed(db, resources=['meeting', 'notification', 'work_task'], scope='self')
    guest = await seed(db, tenant=author.tenant_id, resources=['meeting', 'notification'], scope='self')
    stranger = await seed(db, tenant=author.tenant_id, resources=['meeting', 'notification'], scope='department')
    await db.commit()
    payload = MeetingCreate(operation_id=str(uuid4()), title='项目协调会', agenda='讨论验收安排',
        starts_at=utcnow()+timedelta(days=1), ends_at=utcnow()+timedelta(days=1,hours=1),
        host_id=author.user_id, recorder_id=author.user_id, attendee_ids=[guest.user_id], location='会议室一')
    result = await service.save(db, author, payload)
    await db.commit()
    return author, guest, stranger, payload, result.result


async def test_lifecycle_feedback_replay_and_notification_origin(oa_db):
    async with oa_db() as db:
        author, guest, stranger, payload, row = await setup(db)
        assert (await service.save(db, author, payload)).replayed
        assert await service.list_items(db, guest) == []
        with pytest.raises(AppException): await service.detail(db, guest, row['id'])
        publish = command(row)
        row = (await service.transition(db, author, row['id'], publish, 'publish')).result
        await db.commit()
        assert row['state'] == 'SCHEDULED'
        assert (await service.transition(db, author, row['id'], publish, 'publish')).replayed
        assert len(await service.list_items(db, guest)) == 1
        assert await service.list_items(db, stranger) == []
        from app.services.oa_notification_service import list_inbox
        notices = await list_inbox(db, guest)
        assert len(notices) == 1 and notices[0]['source_kind'] == 'meeting'
        assert notices[0]['object_id'] == row['id']
        reply = MeetingReply(operation_id=str(uuid4()), expected_revision=row['revision'],
            invitation_version=row['invitation_version'], response='ACCEPTED', note='准时参加')
        await service.reply(db, guest, row['id'], reply)
        await db.commit()
        assert (await service.reply(db, guest, row['id'], reply)).replayed
        row = await service.detail(db, author, row['id'])
        assert next(x for x in row['attendees'] if x['user_id']==guest.user_id)['response'] == 'ACCEPTED'
        row = (await service.transition(db, author, row['id'], command(row), 'start')).result
        row = (await service.transition(db, author, row['id'], command(row), 'end')).result
        await db.commit()
        assert row['state']=='ENDED'
        with pytest.raises(AppException): await service.reply(db, guest, row['id'], reply.model_copy(update={'operation_id':str(uuid4())}))
        with pytest.raises(AppException): await service.transition(db, stranger, row['id'], command(row), 'cancel')


async def test_video_admission_waits_before_meeting_lock_when_command_holds_identity_gate(oa_db, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from app.services import identity_service, meeting_video_service as video

    async with oa_db() as db:
        author, guest, _, _, row = await setup(db)
        meeting = await db.get(OAMeeting, row['id'])
        meeting.video_enabled = True
        meeting.state = 'IN_PROGRESS'
        meeting.invitation_version = 1
        await db.commit()

    monkeypatch.setattr(video, 'ensure_room', AsyncMock())
    monkeypatch.setattr(video, 'request', AsyncMock())
    monkeypatch.setattr(video, 'settings', lambda: type('Settings', (), {
        'trtc_sdk_app_id': 42, 'trtc_user_sig_expire_seconds': 600})())
    monkeypatch.setattr(video, 'user_sig', lambda *args, **kwargs: 'test-sig')
    monkeypatch.setattr(video, 'room_password', lambda meeting: '123456')
    attempting_gate = asyncio.Event()
    real_lock = identity_service.lock_tenant

    async def observed_gate(db, tenant):
        attempting_gate.set()
        await real_lock(db, tenant)

    async def admit():
        async with oa_db() as db:
            result = await video.admission(db, guest, row['id'])
            await db.commit()
            return result

    async with oa_db() as command_db:
        await real_lock(command_db, author.tenant_id)
        # Reproduce the user -> meeting half of the production deadlock.
        await command_db.scalar(select(OAUser).where(OAUser.id == guest.user_id).with_for_update())
        monkeypatch.setattr(identity_service, 'lock_tenant', observed_gate)
        task = asyncio.create_task(admit())
        try:
            await asyncio.wait_for(attempting_gate.wait(), timeout=3)
            await asyncio.wait_for(service.access(command_db, author, row['id'], lock=True), timeout=3)
            await command_db.commit()
            result = await asyncio.wait_for(task, timeout=5)
            assert result['userId'] == video.account_id(guest.tenant_id, guest.user_id)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_reschedule_resets_replies_and_revokes_removed_guests(oa_db):
    async with oa_db() as db:
        author, guest, stranger, payload, row = await setup(db)
        row = (await service.transition(db, author, row['id'], command(row), 'publish')).result
        old = dict(row)
        row = (await service.save(db, author, MeetingUpdate(**{**payload.model_dump(), 'operation_id':str(uuid4()),
            'expected_revision':row['revision'], 'attendee_ids':[stranger.user_id],
            'starts_at':payload.starts_at+timedelta(hours=2), 'ends_at':payload.ends_at+timedelta(hours=2)}), row['id'])).result
        await db.commit()
        assert row['invitation_version']==2
        with pytest.raises(AppException): await service.detail(db, guest, row['id'])
        assert len((await service.detail(db, stranger, row['id']))['attendees'])==2
        with pytest.raises(AppException) as error:
            await service.transition(db, author, row['id'], command(old), 'start')
        assert error.value.http_status==409
        from app.services.oa_notification_service import list_inbox
        assert await list_inbox(db, guest)==[]
        row=(await service.transition(db, author, row['id'], command(row, reason='计划取消'), 'cancel')).result
        await db.commit()
        assert row['state']=='CANCELLED'
        with pytest.raises(AppException): await service.transition(db, author, row['id'], command(row), 'start')


async def test_conflicts_do_not_expose_other_meeting_content_and_options_are_minimal(oa_db):
    async with oa_db() as db:
        author, guest, stranger, payload, row = await setup(db)
        await service.transition(db, author, row['id'], command(row), 'publish')
        await db.commit()
        conflicts=await service.conflicts(db, stranger, payload)
        assert {x['user_id'] for x in conflicts}=={author.user_id,guest.user_id}
        assert all(set(x)=={'user_id','display_name','count'} for x in conflicts)
        options=await service.options(db, author)
        assert len(options['users'])==3
        assert all(set(x)=={'id','display_name','department_id'} for x in options['users'])
        with pytest.raises(AppException): await service.save(db, stranger, MeetingUpdate(
            **payload.model_dump(), expected_revision=1), row['id'])
        with pytest.raises(AppException): await service.detail(db, (await seed(db, resources=['meeting'])), row['id'])


async def test_cancelling_an_unpublished_draft_keeps_it_private(oa_db):
    async with oa_db() as db:
        author, guest, _, _, row = await setup(db)
        row = (await service.transition(db, author, row['id'], command(row, reason='暂不召开'), 'cancel')).result
        await db.commit()
        assert row['state'] == 'CANCELLED'
        assert row['invitation_version'] == 0
        assert await service.list_items(db, guest) == []
        with pytest.raises(AppException):
            await service.detail(db, guest, row['id'])
        assert not (await db.scalars(select(OANotification).where(OANotification.tenant_id == author.tenant_id))).all()


@pytest.mark.parametrize('boundary', ['disabled', 'revoked'])
async def test_current_identity_is_required_for_access_and_notifications(oa_db, boundary):
    async with oa_db() as db:
        author, guest, _, _, row=await setup(db)
        await service.transition(db, author, row['id'], command(row), 'publish')
        await db.commit()
        if boundary=='disabled':
            from sqlalchemy import update
            async with oa_db() as admin_db:
                await admin_db.execute(update(OAUser).where(OAUser.id==guest.user_id).values(status='disabled'))
                await admin_db.commit()
        else:
            from sqlalchemy import delete
            roles=select(OAUserRole.role_id).where(OAUserRole.user_id==guest.user_id)
            await db.execute(delete(OARolePermission).where(OARolePermission.tenant_id==guest.tenant_id,
                OARolePermission.role_id.in_(roles)))
            await db.commit()
        with pytest.raises(AppException): await service.detail(db,guest,row['id'])
        from app.services.oa_notification_source import allowed
        notification=await db.scalar(select(OANotification).where(OANotification.tenant_id==guest.tenant_id,
            OANotification.recipient_id==guest.user_id))
        assert not await allowed(db, notification)


async def test_publish_revalidates_members_and_replay_rechecks_roles(oa_db):
    from sqlalchemy import update
    from app.models.oa_meeting import OAMeeting
    async with oa_db() as db:
        author, guest, stranger, payload, row=await setup(db)
        async with oa_db() as admin_db:
            await admin_db.execute(update(OAUser).where(OAUser.id==guest.user_id).values(status='disabled'))
            await admin_db.commit()
        with pytest.raises(AppException,match='参会人'):
            await service.transition(db,author,row['id'],command(row),'publish')
        await db.rollback()
        async with oa_db() as admin_db:
            await admin_db.execute(update(OAUser).where(OAUser.id==guest.user_id).values(status='active'))
            await admin_db.commit()
        row=(await service.transition(db,author,row['id'],command(row),'publish')).result
        await db.commit()
        reply=MeetingReply(operation_id=str(uuid4()),expected_revision=row['revision'],invitation_version=1,response='ACCEPTED')
        await service.reply(db,guest,row['id'],reply)
        await db.commit()
        row=(await service.save(db,author,MeetingUpdate(**{**payload.model_dump(),
            'operation_id':str(uuid4()),'expected_revision':row['revision'],'attendee_ids':[stranger.user_id]}),row['id'])).result
        await db.commit()
        with pytest.raises(AppException): await service.reply(db,guest,row['id'],reply)
        assert (await db.get(OAMeeting,row['id'])).state=='SCHEDULED'


async def test_minutes_visibility_confirmation_notice_and_task_source(oa_db,monkeypatch):
    from app.models.meeting_record import MeetingRecord
    from app.models.meeting_draft_version import MeetingDraftVersion
    from app.models.meeting_decision import MeetingDecision
    from app.models.agent_thread import AgentThread
    from app.models.oa_meeting import OAMeeting
    from app.services import meeting_service as minutes, work_task_service as tasks
    from app.services.oa_notification_service import list_inbox
    async with oa_db() as db:
        author,guest,stranger,_,row=await setup(db)
        for action in ('publish','start','end'):
            row=(await service.transition(db,author,row['id'],command(row),action)).result
        thread=AgentThread(user_id=author.user_id,tenant_id=author.tenant_id,scene='meeting',status='WAITING_HUMAN')
        db.add(thread)
        await db.flush()
        record=MeetingRecord(meeting_id='MTG-'+uuid4().hex,tenant_id=author.tenant_id,owner_id=author.user_id,thread_id=thread.id,
            title='待发布的秘密纪要',status='DRAFT_READY',current_version=1,idempotency_key=uuid4().hex)
        db.add(record)
        await db.flush()
        version=MeetingDraftVersion(meeting_id=record.id,version=1,summary='通过项目验收',topics=[],decisions=[],
            action_items=[],source_refs=[])
        db.add(version)
        (await db.get(OAMeeting,row['id'])).minutes_id=record.meeting_id
        await db.commit()
        assert (await service.detail(db,author,row['id']))['minutes_accessible']
        assert not (await service.detail(db,guest,row['id']))['minutes_accessible']
        with pytest.raises(AppException): await minutes.get_meeting(db,guest,record.meeting_id)
        assert (await minutes.list_meetings(db,stranger)).items==[]
        async def no_graph(*args,**kwargs): pass
        monkeypatch.setattr(minutes,'_scene_available',no_graph)
        monkeypatch.setattr(minutes,'_resume_decision',no_graph)
        result=await minutes.decide(db,author,record.meeting_id,'confirm',None,'confirm-scheduled',expected_version=1)
        await db.commit()
        assert result.status=='CONFIRMED'
        assert (await minutes.get_meeting(db,guest,record.meeting_id)).available_actions==[]
        assert not (await minutes.get_meeting(db,guest,record.meeting_id)).can_create_tasks
        assert (await minutes.get_meeting(db,author,record.meeting_id)).can_create_tasks
        assert any(n['title']=='会议纪要已确认' for n in await list_inbox(db,guest))
        source=await tasks.load_source(db,author,'meeting',record.meeting_id,1)
        assert source['version']=='1'
        with pytest.raises(AppException): await tasks.load_source(db,guest,'meeting',record.meeting_id,1)
        assert await db.scalar(select(MeetingDecision.id).where(MeetingDecision.meeting_id==record.id))


async def test_failed_deliveries_retry_preserves_unknown_and_blocks_guest(oa_db):
    from app.models.oa_notification import OANotificationDelivery
    async with oa_db() as db:
        author,guest,_,_,row=await setup(db)
        row=(await service.transition(db,author,row['id'],command(row),'publish')).result
        await db.commit()
        notices=(await db.scalars(select(OANotification).where(OANotification.tenant_id==author.tenant_id))).all()
        deliveries=[]
        for n,state in zip(notices,['FAILED','UNKNOWN']):
            delivery=OANotificationDelivery(tenant_id=author.tenant_id,notification_id=n.id,channel='wecom',
                state=state,message_id=uuid4().hex,attempt_count=1)
            db.add(delivery);deliveries.append(delivery)
        await db.commit()
        with pytest.raises(AppException): await service.retry_notifications(db,guest,row['id'],command(row))
        await service.retry_notifications(db,author,row['id'],command(row))
        await db.commit()
        assert [d.state for d in deliveries]==['PENDING','UNKNOWN']


@pytest.mark.parametrize('change',[
    {'online_url':'javascript:alert(1)'}, {'online_url':'https://user:password@example.com'},
    {'starts_at':'2026-10-25T10:00:00'}, {'ends_at':'2020-01-01T00:00:00Z'}, {'location':'','online_url':''},
])
def test_meeting_input_rejects_unsafe_or_invalid_fields(change):
    from pydantic import ValidationError
    fields=dict(operation_id='key',title='项目协调会',agenda='讨论安排',starts_at='2026-10-26T10:00:00Z',
        ends_at='2026-10-26T11:00:00Z',host_id='user',recorder_id='user',attendee_ids=['user'],location='会议室')
    with pytest.raises(ValidationError): MeetingCreate(**{**fields,**change})


def test_video_only_meeting_is_a_valid_schedule():
    payload=MeetingCreate(operation_id='video-only',title='视频会议',agenda='线上评审',
        starts_at='2026-10-26T10:00:00Z',ends_at='2026-10-26T11:00:00Z',host_id='user',recorder_id='user',
        attendee_ids=['user'],video_enabled=True)
    assert payload.video_enabled is True and not payload.location and not payload.online_url


async def test_http_commits_permissions_and_manual_meetings_with_ai_disabled(oa_db,monkeypatch):
    import httpx
    from app.main import app
    from app.db.session import get_db
    from app.db import session as sessions
    from app.middleware import auth
    from app.core import config
    from app.services.identity_service import issue
    from app.services import identity_service
    from tests.integration.test_identity_sessions import configured
    async with oa_db() as db:
        author,guest,stranger,payload,row=await setup(db)
        issued=await issue(db,await db.get(OAUser,author.user_id),configured())
        await db.commit()
    settings=configured().model_copy(update={'ai_enabled':False})
    monkeypatch.setattr(config,'get_settings',lambda:settings)
    monkeypatch.setattr(auth,'get_settings',lambda:settings)
    monkeypatch.setattr(identity_service,'get_settings',lambda:settings)
    monkeypatch.setattr(sessions,'async_session_factory',oa_db)
    async def database():
        async with oa_db() as db: yield db
    app.dependency_overrides[get_db]=database
    try:
        headers={'Authorization':'Bearer '+issued.grant.access_token}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.get('/api/meeting-events')).status_code==401
            response=await client.post('/api/meeting-events',headers=headers,json={**payload.model_dump(mode='json'),'operation_id':str(uuid4())})
            assert response.status_code==200,response.text
            saved=response.json()['data']['result']
            response=await client.post('/api/meeting-events/'+saved['id']+'/publish',headers=headers,json=command(saved).model_dump())
            assert response.status_code==200,response.text
            options=await client.get('/api/meeting-events/options',headers=headers)
            assert options.status_code==200,options.text
            assert len(options.json()['data']['users'])==3
            assert (await client.get('/api/meetings',headers=headers)).status_code==503
        async with oa_db() as db:
            assert (await service.detail(db,author,saved['id']))['state']=='SCHEDULED'
    finally: app.dependency_overrides.pop(get_db,None)


async def test_video_session_http_allows_read_only_invitee_but_denies_other_users(oa_db, monkeypatch):
    import httpx
    from sqlalchemy import delete
    from app.main import app
    from app.db.session import get_db
    from app.db import session as sessions
    from app.middleware import auth
    from app.core import config
    from app.services import identity_service, meeting_video_service as video
    from tests.integration.test_identity_sessions import configured

    async with oa_db() as db:
        author, guest, stranger, payload, row = await setup(db)
        outsider = await seed(db, resources=['meeting'], scope='self')
        row = (await service.transition(db, author, row['id'], command(row), 'publish')).result
        row = (await service.transition(db, author, row['id'], command(row), 'start')).result
        model = await db.get(OAMeeting, row['id'])
        model.video_enabled = True
        write_ids = select(OAPermission.id).where(OAPermission.resource == 'meeting', OAPermission.action == 'write')
        role_ids = select(OAUserRole.role_id).where(OAUserRole.user_id == guest.user_id, OAUserRole.tenant_id == guest.tenant_id)
        await db.execute(delete(OARolePermission).where(OARolePermission.role_id.in_(role_ids), OARolePermission.permission_id.in_(write_ids)))
        grants = {}
        for actor in (author, guest, stranger, outsider):
            grant = await identity_service.issue(db, await db.get(OAUser, actor.user_id), configured())
            grants[actor.user_id] = {'Authorization': 'Bearer ' + grant.grant.access_token}
        await db.commit()
    settings = configured()
    monkeypatch.setattr(config, 'get_settings', lambda: settings)
    monkeypatch.setattr(auth, 'get_settings', lambda: settings)
    monkeypatch.setattr(identity_service, 'get_settings', lambda: settings)
    monkeypatch.setattr(sessions, 'async_session_factory', oa_db)
    from unittest.mock import AsyncMock
    monkeypatch.setattr(video, 'ensure_room', AsyncMock())
    monkeypatch.setattr(video, 'request', AsyncMock())
    monkeypatch.setattr(video, 'settings', lambda: type('VideoSettings', (), {
        'trtc_sdk_app_id': 42, 'trtc_user_sig_expire_seconds': 600})())
    monkeypatch.setattr(video, 'user_sig', lambda *args, **kwargs: 'test-sig')
    monkeypatch.setattr(video, 'room_password', lambda row: '123456')

    async def database():
        async with oa_db() as db:
            yield db
    app.dependency_overrides[get_db] = database
    url = '/api/meeting-events/' + row['id']
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post(url + '/video-session', headers=grants[guest.user_id])
            assert response.status_code == 200, response.text
            assert response.headers['cache-control'] == 'no-store, private'
            assert response.json()['data']['userId'] == video.account_id(guest.tenant_id, guest.user_id)
            assert (await client.post(url + '/end', headers=grants[guest.user_id], json=command(row).model_dump())).status_code == 403
            for actor in (stranger, outsider):
                assert (await client.post(url + '/video-session', headers=grants[actor.user_id])).status_code == 404
            ended = await client.post(url + '/end', headers=grants[author.user_id], json=command(row).model_dump())
            assert ended.status_code == 200, ended.text
            assert (await client.post(url + '/video-session', headers=grants[guest.user_id])).status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
