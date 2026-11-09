"""Explicit consent, durable cloud commands, trusted utterances and draft-only automation."""
import asyncio
import hashlib
import logging
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, delete, func
from ..core import config
from ..models.identity import OAUser
from ..models.oa_meeting import OAMeeting, OAMeetingAttendee
from ..models.meeting_transcription import MeetingTranscription as Job, MeetingUtterance as Utterance
from ..providers import meeting_transcription as cloud
from . import meeting_management_service as meetings
from .identity_service import utcnow, current_identity
from .oa_access_service import invalid, denied, revision_conflict

logger = logging.getLogger(__name__)
TERMINAL = {'DRAFT_READY','REVIEW_REQUIRED','FAILED','CANCELLED'}
NOTICE = '仅记录开启后的已收到音频，静音、断网及未收到的回调可能造成缺失，请核对后发布纪要。'
CALLBACK_NOTICE = '尚未收到转写服务回调，请先检查公网回调地址、隧道和签名配置；暂不能据此判断麦克风是否正常。'


async def job_for(db, row, *, lock=False):
    q = select(Job).where(Job.tenant_id == row.tenant_id, Job.meeting_id == row.id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(q)


def controller(actor, row):
    return actor.user_id in {row.organizer_id, row.host_id}


async def status(db, actor, meeting_id):
    actor, row = await meetings.access(db, actor, meeting_id)
    job = await job_for(db, row)
    writable = any(p['resource']=='meeting' and p['action']=='write' for p in actor.data_scope.get('permissions', []))
    result = dict(configured=cloud.configured(), state=job.state if job else 'NOT_STARTED',
        notice=NOTICE, message=job.message if job else '', partial=True,
        can_start=not job and cloud.configured() and writable and controller(actor,row) and
            row.state=='IN_PROGRESS' and row.video_enabled and row.video_room_created,
        can_stop=bool(job and writable and controller(actor,row) and job.state in {'QUEUED','STARTING','ACTIVE','UNKNOWN'}),
        can_retry=bool(job and writable and meetings.editor(actor,row) and row.state=='ENDED' and
            job.state=='REVIEW_REQUIRED' and job.expires_at>utcnow()),
        minutes_id=row.minutes_id if meetings.editor(actor,row) else None, utterances=[], utterance_count=0, expired=False)
    if job:
        result['expired'] = job.expires_at <= utcnow()
        if (not job.last_callback_at and job.created_at <= utcnow()-timedelta(seconds=30) and
                job.state in {'ACTIVE','STOPPING','FINALIZING','READY','REVIEW_REQUIRED'}):
            result['message'] = CALLBACK_NOTICE
        if meetings.editor(actor,row) and not result['expired']:
            result['utterance_count'] = await db.scalar(select(func.count()).select_from(Utterance).where(
                Utterance.tenant_id==row.tenant_id, Utterance.transcription_id==job.id))
            lines = (await db.execute(select(Utterance, OAUser.display_name).join(OAUser,
                (OAUser.id==Utterance.speaker_id) & (OAUser.tenant_id==Utterance.tenant_id)).where(
                Utterance.tenant_id==row.tenant_id, Utterance.transcription_id==job.id)
                .order_by(Utterance.start_ms,Utterance.end_ms,Utterance.segment_key).limit(2000))).all()
            result['utterances'] = [dict(id=u.id,speaker=name,start_ms=u.start_ms,end_ms=u.end_ms,text=u.text,
                late=bool(job.frozen_at and u.created_at>job.frozen_at)) for u,name in lines]
    return result


async def command(db, actor, meeting_id, payload, action):
    actor, row = await meetings.access(db, actor, meeting_id)
    if action=='retry':
        if not meetings.editor(actor,row): raise denied()
    elif not controller(actor,row): raise denied()
    async def perform(operation):
        fresh, locked = await meetings.access(db, actor, meeting_id, lock=True)
        if locked.revision != payload.expected_revision: raise revision_conflict()
        if (action=='retry' and not meetings.editor(fresh,locked)) or (action!='retry' and not controller(fresh,locked)):
            raise denied()
        job = await job_for(db, locked, lock=True)
        if action=='start':
            if locked.state!='IN_PROGRESS' or not locked.video_enabled or not locked.video_room_created:
                raise invalid('请先开始视频会议并加入房间，再开启转写')
            if job: raise invalid('本场会议已有转写任务，请查看当前状态')
            if not cloud.configured(): raise invalid('会议转写尚未配置，请联系管理员')
            if not payload.consent: raise invalid('请先向参会人告知并取得记录授权')
            from .meeting_video_service import room_id
            job = Job(tenant_id=locked.tenant_id,meeting_id=locked.id,initiator_id=fresh.user_id,
                sdk_app_id=config.get_settings().trtc_sdk_app_id,room_id=room_id(locked),
                robot_id='oa_asr_'+uuid4().hex[:24],state='QUEUED',message=NOTICE,
                expires_at=utcnow()+timedelta(days=config.get_settings().meeting_transcription_retention_days))
            db.add(job)
        elif action=='stop':
            if not job: raise invalid('尚未开启转写')
            if job.state not in TERMINAL | {'READY','FINALIZING','GENERATING'}:
                job.stop_requested_at = job.stop_requested_at or utcnow()
                job.next_attempt_at = None
                if job.state=='QUEUED': job.state='CANCELLED'
        elif action=='retry':
            if not job or job.state!='REVIEW_REQUIRED' or locked.state!='ENDED' or job.expires_at<=utcnow():
                raise invalid('当前转写不能重试生成纪要')
            job.state, job.message, job.next_attempt_at = 'READY', NOTICE, None
        await db.flush()
        return await meetings.outcome(db,fresh,locked)
    return await meetings.execute(db,actor,meeting_id,payload,'transcription_'+action,perform)


async def request_stop(db, row):
    job = await job_for(db,row,lock=True)
    if job and job.state not in TERMINAL | {'READY','GENERATING'}:
        job.stop_requested_at = job.stop_requested_at or utcnow()
        job.next_attempt_at = None
        if job.state=='QUEUED': job.state='CANCELLED'


async def receive(db, event, app_id):
    """Only signed 2.0 complete-sentence callbacks enter this function."""
    info = event['EventInfo']
    try:
        robot, task, room = str(info['RobotId']), str(info['TaskId']), str(info['RoomId'])
        payload = info['Payload']
        if not robot or not task or len(task)>256 or not isinstance(payload,dict): raise ValueError()
    except (KeyError,ValueError,TypeError):
        raise invalid('转写事件字段不完整') from None
    job = await db.scalar(select(Job).where(Job.robot_id==robot).with_for_update())
    if not job: raise invalid('未知的转写任务')
    if str(job.sdk_app_id)!=app_id or job.room_id!=room or info.get('RoomIdType')!=1 or (job.task_id and job.task_id!=task):
        raise denied()
    if job.state=='CANCELLED': return
    job.task_id = task
    now = utcnow()
    job.last_callback_at = now
    kind = event['EventType']
    if kind==1401:
        if payload.get('Status')==1 and job.state in {'STARTING','UNKNOWN','QUEUED'}:
            job.state,job.message='FAILED','转写服务启动失败，请核对云端应用配置'
            job.stopped_at=job.stopped_at or now
        elif payload.get('Status')==0 and job.state in {'STARTING','UNKNOWN'}:
            job.state='ACTIVE'
    elif kind==1402:
        job.stopped_at=job.stopped_at or now
        if job.state in {'STARTING','ACTIVE','STOPPING','UNKNOWN'}: job.state='FINALIZING'
    elif kind==1403:
        if job.expires_at<=now:
            job.stop_requested_at=job.stop_requested_at or now
            return
        try:
            user,text,round_id=payload['UserId'],payload['Text'],payload['RoundId']
            start,end=payload['StartUtcMs'],payload['EndUtcMs']
            if not all(isinstance(v,str) and v for v in [user,text,round_id]): raise ValueError()
            if len(text)>20000 or len(round_id)>256 or type(start) is not int or type(end) is not int: raise ValueError()
            if start<0 or end<start or end-start>3600000 or end>int(now.timestamp()*1000)+300000: raise ValueError()
        except (KeyError,ValueError,TypeError): raise invalid('转写句子格式不正确') from None
        from .meeting_video_service import account_id
        people=(await db.scalars(select(OAMeetingAttendee.user_id).where(
            OAMeetingAttendee.tenant_id==job.tenant_id,OAMeetingAttendee.meeting_id==job.meeting_id))).all()
        speaker=next((uid for uid in people if account_id(job.tenant_id,uid)==user),None)
        if not speaker: raise denied()
        key=hashlib.sha256((user+'\n'+round_id).encode()).hexdigest()
        old=await db.scalar(select(Utterance).where(Utterance.tenant_id==job.tenant_id,
            Utterance.transcription_id==job.id,Utterance.segment_key==key))
        if old:
            if (old.text,old.start_ms,old.end_ms)!=(text,start,end):
                job.message='同一语句收到不同内容，请人工核对转写记录'
            return
        count=await db.scalar(select(func.count()).select_from(Utterance).where(
            Utterance.tenant_id==job.tenant_id,Utterance.transcription_id==job.id))
        if count>=10000:
            job.stop_requested_at=job.stop_requested_at or now
            job.message='转写达到单场保存上限，已请求停止，请补充剩余内容'
            return
        db.add(Utterance(tenant_id=job.tenant_id,transcription_id=job.id,speaker_id=speaker,
            segment_key=key,start_ms=start,end_ms=end,text=text))
        if job.frozen_at: job.message='收到迟到的转写文本，已生成的纪要未包含这部分，请人工补充'


async def authorized(db, job, row):
    user=await db.get(OAUser,job.initiator_id)
    actor=await current_identity(db,user)
    actor,_=await meetings.access(db,actor,row.id)
    from .authorization_service import require_permission
    require_permission(actor,'meeting','write')
    if not meetings.editor(actor,row): raise denied()
    return actor


async def process(factory, job_id):
    """Commit the claim BEFORE network IO. An ambiguous create is never repeated."""
    action=None
    async with factory() as db:
        probe=await db.get(Job,job_id)
        if not probe: return
        row=await db.scalar(select(OAMeeting).where(OAMeeting.tenant_id==probe.tenant_id,
            OAMeeting.id==probe.meeting_id).with_for_update())
        job=await db.scalar(select(Job).where(Job.id==job_id).with_for_update(skip_locked=True)
            .execution_options(populate_existing=True))
        if not job or not row: return
        now=utcnow()
        if job.next_attempt_at and job.next_attempt_at>now: return
        if job.state=='STARTING':
            if job.updated_at<now-timedelta(seconds=90):
                job.state,job.message='UNKNOWN','启动结果待核对，请在腾讯控制台检查；系统不会重复创建任务'
            await db.commit()
            return
        if job.state=='GENERATING':
            if job.updated_at<now-timedelta(minutes=5):
                job.state,job.message='REVIEW_REQUIRED','纪要生成被中断，可重试生成或人工处理'
            await db.commit()
            return
        if job.state in TERMINAL: return
        job.next_attempt_at=now+timedelta(seconds=15)
        if job.state=='QUEUED':
            if row.state!='IN_PROGRESS' or job.stop_requested_at or not cloud.configured():
                job.state='CANCELLED'
            else:
                try: await authorized(db,job,row)
                except Exception:
                    job.state,job.message='FAILED','发起人的权限已变化，未开启转写'
                else:
                    job.state='STARTING'
                    action='start'
        elif job.task_id and not job.stopped_at and (job.stop_requested_at or row.state!='IN_PROGRESS' or
                job.expires_at<=now or job.created_at<now-timedelta(hours=8) or not cloud.configured()):
            job.stop_requested_at=job.stop_requested_at or now
            job.state='STOPPING'
            action='stop'
        elif job.state in {'ACTIVE','UNKNOWN'} and job.task_id:
            action='describe'
        elif job.state=='FINALIZING':
            if job.stopped_at and now-job.stopped_at>=timedelta(seconds=90) and (
                    not job.last_callback_at or now-job.last_callback_at>=timedelta(seconds=15)):
                job.state='READY'
        if job.state=='READY' and row.state in {'ENDED','CANCELLED'}:
            if row.state=='CANCELLED': job.state='CANCELLED'
            else:
                job.state='GENERATING'
                job.frozen_at=job.frozen_at or now
                action='generate'
        if action:
            job.attempts+=1
            job.next_attempt_at=now+timedelta(seconds=15 if action=='describe' else 10)
        await db.commit()
        # Scalar copies survive session shutdown and keep credentials out of the ledger.
        data=dict(app_id=job.sdk_app_id,room_id=job.room_id,robot_id=job.robot_id,task_id=job.task_id)
    if action=='generate':
        await generate(factory,job_id)
        return
    if not action: return
    try:
        if action=='start':
            from .meeting_video_service import user_sig
            result=await cloud.request('CreateCloudTranscription',dict(SdkAppId=data['app_id'],RoomId=data['room_id'],RoomIdType=1,
                TranscriptionParam=dict(UserId=data['robot_id'],UserSig=user_sig(data['robot_id']),MaxIdleTime=60,SendCustomMode=0),
                AsrParam=dict(Lang=config.get_settings().meeting_transcription_language)))
            if not result.get('TaskId'): raise ValueError('missing task id')
        else:
            result=await cloud.request('DeleteCloudTranscription' if action=='stop' else 'DescribeCloudTranscription',
                dict(SdkAppId=data['app_id'],TaskId=data['task_id']))
    except Exception as exc:
        code=getattr(exc,'code','') or (exc.get_code() if hasattr(exc,'get_code') else '')
        # A missing task after an idempotent stop means it is already gone.
        missing=code in {'ResourceNotFound','ResourceNotFound.TaskId','FailedOperation.TaskNotExist'}
        async with factory() as db:
            job=await db.scalar(select(Job).where(Job.id==job_id).with_for_update())
            if not job or job.state in TERMINAL: return
            if action=='start' and not job.task_id:
                job.state,job.message='UNKNOWN','启动结果待核对，请检查腾讯控制台；系统不会重复创建任务'
            elif missing and action in {'stop','describe'}:
                job.stopped_at=utcnow()
                job.state='FINALIZING'
                job.message='转写服务已退出，请核对是否存在音频或文本缺失'
            else:
                job.message='转写服务连接异常，正在核对任务；请勿将当前文本视为完整记录'
                job.next_attempt_at=utcnow()+timedelta(seconds=30)
            await db.commit()
        logger.warning('会议转写云端操作未完成: %s',action)
        return
    async with factory() as db:
        job=await db.scalar(select(Job).where(Job.id==job_id).with_for_update())
        if not job or job.state in TERMINAL: return
        if action=='start':
            if job.task_id and job.task_id!=result['TaskId']:
                job.state,job.message='UNKNOWN','云端任务与回调不一致，请人工核对'
            else:
                job.task_id=result['TaskId']
                if job.state=='STARTING': job.state='ACTIVE'
        elif action=='stop' or result.get('Status')=='Exited':
            job.stopped_at=job.stopped_at or utcnow()
            job.state='FINALIZING'
        elif result.get('Status')=='Idle':
            job.message='转写任务当前空闲，请核对音频发布和回调链路；该状态不能单独判定麦克风故障'
        await db.commit()


async def generate(factory, job_id):
    try:
        async with factory() as db:
            job=await db.get(Job,job_id)
            row=await db.scalar(select(OAMeeting).where(OAMeeting.tenant_id==job.tenant_id,
                OAMeeting.id==job.meeting_id).with_for_update())
            actor=await authorized(db,job,row)
            if row.state!='ENDED': raise invalid('会议尚未结束')
            from .meeting_service import create_meeting
            from ..schemas.meeting import MeetingInput
            lines=(await db.execute(select(Utterance,OAUser.display_name).join(OAUser,
                (OAUser.id==Utterance.speaker_id)&(OAUser.tenant_id==Utterance.tenant_id)).where(
                Utterance.tenant_id==job.tenant_id,Utterance.transcription_id==job.id,Utterance.created_at<=job.frozen_at)
                .order_by(Utterance.start_ms,Utterance.end_ms,Utterance.segment_key))).all()
            if not lines: raise invalid('未收到可生成纪要的转写文本，请人工补录')
            if not row.minutes_id:
                from datetime import datetime,timezone
                text='记录范围提示：'+NOTICE+'\n'
                for u,name in lines:
                    stamp=datetime.fromtimestamp(u.start_ms/1000,timezone.utc).isoformat()
                    text+=f'[{stamp}] {name}：{u.text}\n'
                if len(text)>100000: raise invalid('会议文本过长，请人工分段整理')
                minutes=await create_meeting(db,actor,MeetingInput(title=row.title,content=text,source_type='api',
                    idempotency_key='transcription:'+job.id))
                row.minutes_id=minutes.meeting_id
                row.revision+=1
                await db.commit()
            else:
                from ..models.meeting_record import MeetingRecord
                from . import idempotency_service
                record=await db.scalar(select(MeetingRecord).where(MeetingRecord.tenant_id==job.tenant_id,
                    MeetingRecord.meeting_id==row.minutes_id))
                if not record or record.idempotency_key!=idempotency_service.payload_digest(
                        {'actor':actor.user_id,'key':'transcription:'+job.id}):
                    raise invalid('本场会议已有其他纪要，请人工合并转写内容')
            minutes_id=row.minutes_id
        async with factory() as db:
            job=await db.get(Job,job_id)
            row=await db.get(OAMeeting,job.meeting_id)
            actor=await authorized(db,job,row)
            from .meeting_service import generate_draft
            from ..models.meeting_record import MeetingRecord
            record=await db.scalar(select(MeetingRecord).where(MeetingRecord.tenant_id==job.tenant_id,
                MeetingRecord.meeting_id==minutes_id))
            if record.status in {'CREATED','PAUSED'}:
                response=await generate_draft(db,actor,minutes_id,idempotency_key='asr:'+job.id+':'+str(record.error_trace_id or 'initial'),
                    retry=record.status=='PAUSED')
                ready=response.status in {'DRAFT_READY','REVIEWING','CONFIRMED'}
            else: ready=record.status in {'DRAFT_READY','REVIEWING','CONFIRMED'}
            await db.commit()
        async with factory() as db:
            job=await db.scalar(select(Job).where(Job.id==job_id).with_for_update())
            job.state='DRAFT_READY' if ready else 'REVIEW_REQUIRED'
            job.message='纪要草稿已生成，请人工核对转写范围并确认发布' if ready else '模型生成未完成，可重试或打开纪要人工处理'
            await db.commit()
    except Exception:
        async with factory() as db:
            job=await db.scalar(select(Job).where(Job.id==job_id).with_for_update())
            job.state,job.message='REVIEW_REQUIRED','自动纪要未完成，请检查权限、模型配置或转写内容后重试；也可人工整理'
            await db.commit()
        logger.warning('会议转写纪要需要人工处理')


async def tick(factory):
    async with factory() as db:
        ids=(await db.scalars(select(Job.id).where(Job.state.not_in(TERMINAL),
            (Job.next_attempt_at.is_(None)) | (Job.next_attempt_at<=utcnow()))
            .where((Job.state!='STARTING') | (Job.updated_at<utcnow()-timedelta(seconds=90)))
            .where((Job.state!='GENERATING') | (Job.updated_at<utcnow()-timedelta(minutes=5)))
            .order_by(Job.next_attempt_at.asc().nulls_first(),Job.created_at).limit(100))).all()
    for jid in ids:
        await process(factory,jid)
    async with factory() as db:
        expired=select(Job.id).where(Job.expires_at<=utcnow(),Job.state.in_(TERMINAL|{'READY'}))
        await db.execute(delete(Utterance).where(Utterance.transcription_id.in_(expired)))
        await db.commit()


async def run(stop_event):
    from ..db.session import async_session_factory
    while not stop_event.is_set():
        try: await tick(async_session_factory)
        except Exception: logger.warning('会议转写扫描未完成，将在下轮重试')
        try: await asyncio.wait_for(stop_event.wait(),timeout=5)
        except asyncio.TimeoutError: pass
