"""No paid calls: tenant/access, signed real-format callbacks and durable crash handling."""
import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, func, delete, update
from app.core import config
from app.core.errors import AppException
from app.models.identity import OAUser
from app.models.oa_meeting import OAMeeting
from app.models.meeting_transcription import MeetingTranscription as Job, MeetingUtterance as Utterance
from app.schemas.oa_meeting import MeetingCommand, MeetingTranscriptionStart
from app.services import meeting_transcription_service as service
from app.services import meeting_management_service as meetings
from app.services.identity_service import utcnow
from app.services.meeting_video_service import account_id
from app.providers import meeting_transcription as cloud
from tests.oa_support import oa_db
from tests.api.test_meeting_management import setup
from tests.integration.test_identity_sessions import configured


@pytest.fixture(autouse=True)
async def clean_jobs(oa_db):
    # oa_db validates the disposable *_test database before this fixture runs.
    async with oa_db() as db:
        await db.execute(delete(Utterance))
        await db.execute(delete(Job))
        await db.commit()
    yield
    async with oa_db() as db:
        await db.execute(delete(Utterance))
        await db.execute(delete(Job))
        await db.commit()


def enable(monkeypatch):
    s=configured().model_copy(update=dict(meeting_transcription_enabled=True,trtc_sdk_app_id=12345,
        trtc_sdk_secret_key=SecretStr('test-sdk-key'),meeting_transcription_secret_id=SecretStr('test-id'),
        meeting_transcription_secret_key=SecretStr('test-key'),meeting_transcription_callback_key=SecretStr('a'*24),
        meeting_transcription_callback_url='https://oa.example.test/api/meeting-transcriptions/callback/trtc'))
    monkeypatch.setattr(config,'get_settings',lambda:s)
    return s


async def running(db,monkeypatch):
    author,guest,stranger,payload,result=await setup(db)
    enable(monkeypatch)
    row=await db.get(OAMeeting,result['id'])
    row.video_enabled,row.video_room_created,row.state,row.invitation_version=True,True,'IN_PROGRESS',1
    await db.commit()
    return author,guest,stranger,row


async def enqueue(db,actor,row):
    payload=MeetingTranscriptionStart(operation_id=str(uuid4()),expected_revision=row.revision,consent=True)
    await service.command(db,actor,row.id,payload,'start')
    await db.commit()
    return await service.job_for(db,row),payload


def event(job,user,*,kind=1403,round_id='sentence-1',text='下周一完成项目验收。',start=None):
    start=start or int(time.time()*1000)-1000
    return dict(EventGroupId=14,EventType=kind,CallbackTs=int(time.time()*1000),EventInfo=dict(
        TaskId='task-test',RobotId=job.robot_id,RoomId=job.room_id,RoomIdType=1,EventMsTs=int(time.time()*1000),
        Payload=dict(UserId=account_id(job.tenant_id,user),Text=text,RoundId=round_id,
            StartTimeMs=0,EndTimeMs=1000,StartUtcMs=start,EndUtcMs=start+500,Status=0)))


def signed(event):
    raw=json.dumps(event,ensure_ascii=False).encode()
    sign=base64.b64encode(hmac.new(b'a'*24,raw,hashlib.sha256).digest()).decode()
    return raw,sign


async def test_consent_access_replay_and_transcript_privacy(oa_db,monkeypatch):
    async with oa_db() as db:
        author,guest,stranger,row=await running(db,monkeypatch)
        with pytest.raises(ValidationError): MeetingTranscriptionStart(operation_id='x',expected_revision=1,consent=False)
        with pytest.raises(AppException):
            await service.command(db,guest,row.id,MeetingTranscriptionStart(operation_id='guest',expected_revision=row.revision,consent=True),'start')
        job,payload=await enqueue(db,author,row)
        assert (await service.command(db,author,row.id,payload,'start')).replayed
        assert await db.scalar(select(func.count()).select_from(Job).where(Job.meeting_id==row.id))==1
        evt=event(job,guest.user_id)
        raw,sign=signed(evt)
        verified=cloud.verify_callback(raw,sign,'12345')
        await service.receive(db,verified,'12345')
        await service.receive(db,verified,'12345')
        await db.commit()
        assert len((await service.status(db,author,row.id))['utterances'])==1
        assert (await service.status(db,guest,row.id))['utterances']==[]
        with pytest.raises(AppException): await service.status(db,stranger,row.id)
        with pytest.raises(AppException): cloud.verify_callback(raw,sign+'bad','12345')
        with pytest.raises(AppException): cloud.verify_callback(raw,sign,'54321')
        evt['CallbackTs']=1
        with pytest.raises(AppException): cloud.verify_callback(*signed(evt),'12345')


@pytest.mark.parametrize('state', ['ACTIVE', 'FINALIZING', 'REVIEW_REQUIRED'])
async def test_missing_callbacks_are_not_reported_as_microphone_failure(oa_db,monkeypatch,state):
    async with oa_db() as db:
        author,guest,stranger,row=await running(db,monkeypatch)
        job,_=await enqueue(db,author,row)
        job.state=state
        job.created_at=utcnow()-timedelta(minutes=1)
        job.message='旧的状态提示'
        await db.commit()
        result=await service.status(db,author,row.id)
        assert result['state']==state
        assert result['message']==service.CALLBACK_NOTICE
        assert result['utterance_count']==0
        job.last_callback_at=utcnow()
        await db.commit()
        assert (await service.status(db,author,row.id))['message']=='旧的状态提示'


async def test_idle_cloud_task_does_not_diagnose_microphone_failure(oa_db,monkeypatch):
    async with oa_db() as db:
        author,guest,stranger,row=await running(db,monkeypatch)
        job,_=await enqueue(db,author,row)
        job.state,job.task_id='ACTIVE','task-test'
        job.last_callback_at=utcnow()
        jid=job.id
        await db.commit()
    request=AsyncMock(return_value={'Status':'Idle'})
    monkeypatch.setattr(cloud,'request',request)
    await service.process(oa_db,jid)
    assert request.call_args.args[0]=='DescribeCloudTranscription'
    async with oa_db() as db:
        job=await db.get(Job,jid)
        assert job.state=='ACTIVE'
        assert '当前空闲' in job.message
        assert '不能单独判定麦克风故障' in job.message


async def test_callback_binding_order_and_late_text(oa_db,monkeypatch):
    async with oa_db() as db:
        author,guest,stranger,row=await running(db,monkeypatch)
        job,_=await enqueue(db,author,row)
        bad=event(job,guest.user_id)
        bad['EventInfo']['RoomId']='wrong-room'
        with pytest.raises(AppException): await service.receive(db,bad,'12345')
        with pytest.raises(AppException): await service.receive(db,event(job,stranger.user_id),'12345')
        now=int(time.time()*1000)
        await service.receive(db,event(job,author.user_id,round_id='later',start=now),'12345')
        await service.receive(db,event(job,guest.user_id,round_id='earlier',start=now-2000),'12345')
        await db.commit()
        lines=(await service.status(db,author,row.id))['utterances']
        assert [x['speaker'] for x in lines] # both current names are resolved through local users
        assert lines[0]['start_ms']<lines[1]['start_ms']
        job.frozen_at=utcnow()-timedelta(seconds=1)
        await service.receive(db,event(job,guest.user_id,round_id='late'),'12345')
        await db.commit()
        assert '迟到' in job.message
        assert any(x['late'] for x in (await service.status(db,author,row.id))['utterances'])


async def test_uncertain_create_never_repeats_and_callback_reconciles(oa_db,monkeypatch):
    async with oa_db() as db:
        author,guest,_,row=await running(db,monkeypatch)
        job,_=await enqueue(db,author,row)
        jid=job.id
    request=AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(cloud,'request',request)
    await service.process(oa_db,jid)
    async with oa_db() as db:
        job=await db.get(Job,jid)
        assert job.state=='UNKNOWN'
        job.next_attempt_at=None
        await db.commit()
    await service.process(oa_db,jid)
    assert request.await_count==1
    async with oa_db() as db:
        job=await db.get(Job,jid)
        await service.receive(db,event(job,guest.user_id,kind=1401),'12345')
        await db.commit()
        assert job.state=='ACTIVE' and job.task_id=='task-test'


async def test_revocation_blocks_cloud_start_and_retention_removes_only_raw(oa_db,monkeypatch):
    async with oa_db() as db:
        author,guest,_,row=await running(db,monkeypatch)
        job,_=await enqueue(db,author,row)
        jid=job.id
    async with oa_db() as db:
        await db.execute(update(OAUser).where(OAUser.id==author.user_id).values(status='disabled'))
        await db.commit()
    request=AsyncMock()
    monkeypatch.setattr(cloud,'request',request)
    await service.process(oa_db,jid)
    request.assert_not_awaited()
    async with oa_db() as db:
        job=await db.get(Job,jid)
        assert job.state=='FAILED'
        job.expires_at=utcnow()-timedelta(seconds=1)
        db.add(Utterance(tenant_id=job.tenant_id,transcription_id=jid,speaker_id=guest.user_id,
            segment_key='expiry',start_ms=1,end_ms=2,text='到期文本'))
        await db.commit()
    await service.tick(oa_db)
    async with oa_db() as db:
        assert await db.get(Job,jid)
        assert await db.scalar(select(func.count()).select_from(Utterance).where(Utterance.transcription_id==jid))==0


async def test_end_stops_cloud_and_settles_before_draft_only(oa_db,monkeypatch):
    async with oa_db() as db:
        author,guest,_,row=await running(db,monkeypatch)
        job,_=await enqueue(db,author,row)
        jid=job.id
    request=AsyncMock(return_value={'TaskId':'task-test'})
    monkeypatch.setattr(cloud,'request',request)
    monkeypatch.setattr('app.services.meeting_video_service.close_room',AsyncMock())
    await service.process(oa_db,jid)
    assert request.call_args.args[0]=='CreateCloudTranscription'
    assert request.call_args.args[1]['RoomIdType']==1
    assert 'TranslationParam' not in request.call_args.args[1]
    async with oa_db() as db:
        job=await db.get(Job,jid)
        await service.receive(db,event(job,guest.user_id),'12345')
        row=await db.get(OAMeeting,job.meeting_id)
        await meetings.transition(db,author,row.id,MeetingCommand(operation_id=str(uuid4()),expected_revision=row.revision),'end')
        await db.commit()
        assert job.stop_requested_at
        job.next_attempt_at=None
        await db.commit()
    await service.process(oa_db,jid)
    assert request.call_args.args[0]=='DeleteCloudTranscription'
    generate=AsyncMock()
    monkeypatch.setattr(service,'generate',generate)
    await service.process(oa_db,jid)
    generate.assert_not_awaited()
    async with oa_db() as db:
        job=await db.get(Job,jid)
        job.stopped_at=utcnow()-timedelta(seconds=100)
        job.last_callback_at=utcnow()-timedelta(seconds=20)
        job.next_attempt_at=None
        await db.commit()
    await service.process(oa_db,jid)
    generate.assert_awaited_once_with(oa_db,jid)
    async with oa_db() as db:
        assert (await db.get(Job,jid)).frozen_at


async def test_generation_creates_one_reviewable_draft_and_never_confirms(oa_db,monkeypatch):
    from types import SimpleNamespace
    from app.services import meeting_service as minutes
    from app.models.meeting_record import MeetingRecord
    from app.models.meeting_decision import MeetingDecision
    from app.models.meeting_segment import MeetingSegment
    async with oa_db() as db:
        author,guest,_,row=await running(db,monkeypatch)
        job,_=await enqueue(db,author,row)
        await service.receive(db,event(job,guest.user_id),'12345')
        await db.flush()
        row.state='ENDED'
        job.state,job.frozen_at='GENERATING',utcnow()
        jid,mid=job.id,row.id
        await db.commit()
    async def invoke(thread_id,payload):
        return {'draft':dict(summary='下周一完成项目验收。',topics=['项目验收'],decisions=[],action_items=[],
            source_refs=[payload['segments'][0]['segment_id']])}
    fake_runtime=SimpleNamespace(ready=False,get_state=AsyncMock(return_value=SimpleNamespace(values={},next=())),invoke=AsyncMock(side_effect=invoke))
    monkeypatch.setattr(minutes,'runtime',fake_runtime)
    monkeypatch.setattr(minutes,'_scene_available',AsyncMock())
    await service.generate(oa_db,jid)
    await service.generate(oa_db,jid)
    async with oa_db() as db:
        job=await db.get(Job,jid)
        row=await db.get(OAMeeting,mid)
        record=await db.scalar(select(MeetingRecord).where(MeetingRecord.meeting_id==row.minutes_id))
        assert job.state=='DRAFT_READY'
        assert record.status=='DRAFT_READY' and record.current_version==1
        assert await db.scalar(select(func.count()).select_from(MeetingRecord).where(MeetingRecord.tenant_id==author.tenant_id))==1
        assert await db.scalar(select(func.count()).select_from(MeetingDecision).where(MeetingDecision.meeting_id==record.id))==0
        segments=(await db.scalars(select(MeetingSegment).where(MeetingSegment.meeting_id==record.id))).all()
        assert any('项目验收' in part.text for part in segments)
        await service.receive(db,event(job,guest.user_id,round_id='after-draft',text='补充讨论内容。'),'12345')
        await service.receive(db,event(job,guest.user_id,kind=1401),'12345')
        await service.receive(db,event(job,guest.user_id,kind=1402),'12345')
        await db.commit()
        assert job.state=='DRAFT_READY'
        assert '迟到' in job.message
    assert fake_runtime.invoke.await_count==1


async def test_signed_http_callback_and_status_privacy(oa_db,monkeypatch):
    import httpx
    from app.main import app
    from app.db.session import get_db
    from app.db import session as sessions
    from app.middleware import auth
    from app.services import identity_service
    async with oa_db() as db:
        author,guest,_,row=await running(db,monkeypatch)
        job,_=await enqueue(db,author,row)
        raw,sign=signed(event(job,guest.user_id))
        issued=await identity_service.issue(db,await db.get(OAUser,guest.user_id),config.get_settings())
        mid=row.id
        await db.commit()
    settings=config.get_settings()
    monkeypatch.setattr(auth,'get_settings',lambda:settings)
    monkeypatch.setattr(identity_service,'get_settings',lambda:settings)
    monkeypatch.setattr(sessions,'async_session_factory',oa_db)
    async def database():
        async with oa_db() as db: yield db
    app.dependency_overrides[get_db]=database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.post('/api/meeting-transcriptions/callback/trtc',content=raw)).status_code==403
            assert (await client.post('/api/meeting-transcriptions/callback/trtc',content=raw,
                headers={'SdkAppId':'12345','Sign':sign})).json()=={'code':0}
            assert (await client.get('/api/meeting-transcriptions/'+mid)).status_code==401
            headers={'Authorization':'Bearer '+issued.grant.access_token}
            result=await client.get('/api/meeting-transcriptions/'+mid,headers=headers)
            assert result.status_code==200,result.text
            assert result.headers['Cache-Control']=='no-store, private'
            assert result.json()['data']['utterances']==[]
            assert (await client.post('/api/meeting-transcriptions/'+mid+'/start',headers=headers,
                json={'operation_id':str(uuid4()),'expected_revision':1,'consent':False})).status_code==422
            assert (await client.post('/api/meeting-transcriptions/'+mid+'/stop',headers=headers,
                json={'operation_id':str(uuid4()),'expected_revision':1})).status_code==403
    finally:
        app.dependency_overrides.pop(get_db,None)


@pytest.mark.parametrize('raw',[b'\xff',b'[]',b'{}',b'{"EventGroupId":14,"CallbackTs":NaN}',
    b'{"EventGroupId":14,"CallbackTs":true}'])
def test_malformed_signed_callbacks_are_rejected(monkeypatch,raw):
    enable(monkeypatch)
    sign=base64.b64encode(hmac.new(b'a'*24,raw,hashlib.sha256).digest()).decode()
    with pytest.raises(AppException): cloud.verify_callback(raw,sign,'12345')


async def test_expired_unknown_task_reconciles_for_shutdown_without_saving_text(oa_db,monkeypatch):
    async with oa_db() as db:
        author,guest,_,row=await running(db,monkeypatch)
        job,_=await enqueue(db,author,row)
        job.state='UNKNOWN'
        job.expires_at=utcnow()-timedelta(seconds=1)
        jid=job.id
        await service.receive(db,event(job,guest.user_id),'12345')
        await db.commit()
        assert job.task_id=='task-test' and job.stop_requested_at
        assert await db.scalar(select(func.count()).select_from(Utterance).where(Utterance.transcription_id==jid))==0
    request=AsyncMock(return_value={})
    monkeypatch.setattr(cloud,'request',request)
    await service.process(oa_db,jid)
    assert request.call_args.args[0]=='DeleteCloudTranscription'


@pytest.mark.parametrize('failed',[False,True])
async def test_delayed_cloud_result_does_not_reopen_a_completed_draft(oa_db,monkeypatch,failed):
    async with oa_db() as db:
        author,_,_,row=await running(db,monkeypatch)
        job,_=await enqueue(db,author,row)
        job.state,job.task_id='ACTIVE','task-test'
        jid=job.id
        await db.commit()
    async def delayed(*args):
        async with oa_db() as db:
            job=await db.get(Job,jid)
            job.state,job.message='DRAFT_READY','草稿待审阅'
            await db.commit()
        if failed: raise TimeoutError()
        return {'Status':'Exited'}
    monkeypatch.setattr(cloud,'request',delayed)
    await service.process(oa_db,jid)
    async with oa_db() as db:
        job=await db.get(Job,jid)
        assert (job.state,job.message)==('DRAFT_READY','草稿待审阅')


@pytest.mark.parametrize('active',[False,True])
async def test_disabling_transcription_cancels_queued_or_stops_active_tasks(oa_db,monkeypatch,active):
    async with oa_db() as db:
        author,_,_,row=await running(db,monkeypatch)
        job,_=await enqueue(db,author,row)
        jid=job.id
        if active: job.state,job.task_id='ACTIVE','task-test'
        await db.commit()
    config.get_settings().meeting_transcription_enabled=False
    request=AsyncMock(return_value={})
    monkeypatch.setattr(cloud,'request',request)
    await service.process(oa_db,jid)
    async with oa_db() as db:
        assert (await db.get(Job,jid)).state==('FINALIZING' if active else 'CANCELLED')
    if active: assert request.call_args.args[0]=='DeleteCloudTranscription'
    else: request.assert_not_awaited()
