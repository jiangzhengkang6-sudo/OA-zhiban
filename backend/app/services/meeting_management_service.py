"""Tenant-scoped meeting invitations, explicit transitions and transactional notices."""
from uuid import NAMESPACE_URL, uuid5
from sqlalchemy import select, or_, func, delete
from ..core.errors import not_found, AppException
from ..models.identity import OAUser, OAMembership, OADepartment
from ..models.oa_meeting import OAMeeting, OAMeetingAttendee
from ..models.oa_notification import OANotification, OANotificationDelivery
from ..models.oa_workflow import OAWorkflowEvent, OAWorkflowOutbox, OAWorkflowOperation
from .authorization_service import require_permission
from .identity_service import current_identity, utcnow
from .oa_access_service import builtin_actor, OAAccessTarget, invalid, denied, revision_conflict
from .oa_command_service import OACommand, CommandOutcome, run_command


async def identity(db, actor, action='read'):
    actor = await builtin_actor(db, actor)
    require_permission(actor, 'meeting', action)
    return actor


def participation(actor, row):
    return select(OAMeetingAttendee.id).where(OAMeetingAttendee.tenant_id == actor.tenant_id,
        OAMeetingAttendee.meeting_id == row.id, OAMeetingAttendee.user_id == actor.user_id).exists()


async def access(db, actor, meeting_id, *, lock=False):
    actor = await identity(db, actor, 'write' if lock else 'read')
    query = select(OAMeeting).where(OAMeeting.tenant_id == actor.tenant_id, OAMeeting.id == meeting_id,
        or_(OAMeeting.organizer_id == actor.user_id,
            (OAMeeting.invitation_version > 0) & participation(actor, OAMeeting)))
    if lock: query = query.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(query)
    if not row: raise not_found('会议不存在或不可访问')
    return actor, row


async def options(db, actor):
    actor = await identity(db, actor, 'write')
    rows = (await db.execute(select(OAUser, OAMembership.department_id).join(OAMembership,
        (OAMembership.tenant_id == OAUser.tenant_id) & (OAMembership.user_id == OAUser.id)).join(OADepartment,
        (OADepartment.tenant_id == OAMembership.tenant_id) & (OADepartment.id == OAMembership.department_id))
        .where(OAUser.tenant_id == actor.tenant_id, OAUser.status == 'active', OADepartment.enabled.is_(True))
        .order_by(OAUser.display_name, OAUser.id))).all()
    users = []
    for user, department_id in rows:
        member = await current_identity(db, user)
        try: require_permission(member, 'meeting', 'read')
        except AppException: continue
        users.append(dict(id=user.id, display_name=user.display_name, department_id=department_id))
    departments = (await db.scalars(select(OADepartment).where(OADepartment.tenant_id == actor.tenant_id,
        OADepartment.enabled.is_(True)).order_by(OADepartment.name))).all()
    return dict(users=users, departments=[dict(id=d.id, name=d.name) for d in departments])


async def members(db, actor, payload):
    ids = sorted(set([*payload.attendee_ids, actor.user_id, payload.host_id, payload.recorder_id]))
    if len(ids) > 100: raise invalid('每场会议最多安排 100 人')
    available = {x['id'] for x in (await options(db, actor))['users']}
    if not set(ids).issubset(available): raise invalid('参会人不存在、已停用或没有会议访问权限')
    for user_id in {payload.host_id, payload.recorder_id}:
        member = await current_identity(db, await db.get(OAUser, user_id))
        require_permission(member, 'meeting', 'write')
    return ids


def editor(actor, row):
    return actor.user_id in {row.organizer_id, row.host_id, row.recorder_id}


async def view(db, actor, row, *, full=True):
    attendees = (await db.execute(select(OAMeetingAttendee, OAUser.display_name).join(OAUser,
        (OAUser.id == OAMeetingAttendee.user_id) & (OAUser.tenant_id == OAMeetingAttendee.tenant_id))
        .where(OAMeetingAttendee.tenant_id == actor.tenant_id, OAMeetingAttendee.meeting_id == row.id)
        .order_by(OAUser.display_name, OAUser.id))).all()
    own = row.organizer_id == actor.user_id
    writable = any(p['resource']=='meeting' and p['action']=='write' for p in actor.data_scope.get('permissions', []))
    actions = []
    if writable:
        if own and row.state in {'DRAFT', 'SCHEDULED'}: actions.append('edit')
        if own and row.state == 'DRAFT': actions.append('publish')
        if own and row.state in {'DRAFT','SCHEDULED','IN_PROGRESS'}: actions.append('cancel')
        if actor.user_id in {row.organizer_id,row.host_id}:
            if row.state == 'SCHEDULED': actions.append('start')
            if row.state == 'IN_PROGRESS': actions.append('end')
        if row.state == 'SCHEDULED': actions.append('reply')
        if editor(actor,row) and row.state == 'ENDED': actions.append('minutes')
    data = dict(id=row.id, title=row.title, agenda=row.agenda if full else '', organizer_id=row.organizer_id,
        host_id=row.host_id, recorder_id=row.recorder_id, starts_at=row.starts_at.isoformat(), ends_at=row.ends_at.isoformat(),
        location=row.location, online_url=row.online_url, video_enabled=row.video_enabled, state=row.state, revision=row.revision,
        invitation_version=row.invitation_version, minutes_id=row.minutes_id, cancel_reason=row.cancel_reason,
        available_actions=actions, attendees=[dict(user_id=a.user_id, display_name=name, response=a.response,
            note=a.note if editor(actor,row) or a.user_id==actor.user_id else '',
            replied_at=a.replied_at.isoformat() if a.replied_at else None) for a,name in attendees])
    from ..models.meeting_record import MeetingRecord
    minutes = await db.scalar(select(MeetingRecord).where(MeetingRecord.tenant_id==actor.tenant_id,
        MeetingRecord.meeting_id==row.minutes_id)) if row.minutes_id else None
    data['minutes_accessible'] = bool(minutes and (editor(actor,row) or minutes.status=='CONFIRMED'))
    data['minutes_status'] = minutes.status if data['minutes_accessible'] else None
    if full:
        events = (await db.scalars(select(OAWorkflowEvent).where(OAWorkflowEvent.tenant_id==actor.tenant_id,
            OAWorkflowEvent.target_id==row.id, OAWorkflowEvent.action.like('meeting.%'))
            .order_by(OAWorkflowEvent.created_at,OAWorkflowEvent.id))).all()
        data['history']=[dict(action=e.action,actor_id=e.actor_id,created_at=e.created_at.isoformat()) for e in events]
        data['deliveries']=[]
        if own:
            notices=(await db.scalars(select(OANotification).where(OANotification.tenant_id==actor.tenant_id,
                OANotification.source['kind'].as_string()=='meeting',
                OANotification.source['object_id'].as_string()==row.id))).all()
            for n in notices:
                if n.source.get('kind')!='meeting' or n.source.get('object_id')!=row.id: continue
                deliveries=(await db.scalars(select(OANotificationDelivery).where(
                    OANotificationDelivery.tenant_id==actor.tenant_id,OANotificationDelivery.notification_id==n.id))).all()
                data['deliveries'].extend(dict(id=d.id,recipient_id=n.recipient_id,channel=d.channel,
                    state=d.state,attempt_count=d.attempt_count,last_code=d.last_code) for d in deliveries)
    return data


async def detail(db, actor, meeting_id):
    actor, row = await access(db, actor, meeting_id)
    return await view(db, actor, row)


async def list_items(db, actor, mode='all'):
    actor = await identity(db, actor)
    query=select(OAMeeting).where(OAMeeting.tenant_id==actor.tenant_id,
        or_(OAMeeting.organizer_id==actor.user_id,(OAMeeting.invitation_version>0) & participation(actor,OAMeeting)))
    if mode=='organized': query=query.where(OAMeeting.organizer_id==actor.user_id)
    if mode=='invited': query=query.where(OAMeeting.organizer_id!=actor.user_id)
    rows=(await db.scalars(query.order_by(OAMeeting.starts_at.desc(),OAMeeting.id).limit(200))).all()
    return [await view(db,actor,row,full=False) for row in rows]


async def conflicts(db, actor, payload, exclude_id=None):
    actor = await identity(db, actor, 'write')
    ids=await members(db,actor,payload)
    query=select(OAMeetingAttendee.user_id,OAUser.display_name,func.count()).join(OAMeeting,
        (OAMeeting.id==OAMeetingAttendee.meeting_id)&(OAMeeting.tenant_id==OAMeetingAttendee.tenant_id)).join(OAUser,
        (OAUser.id==OAMeetingAttendee.user_id)&(OAUser.tenant_id==OAMeetingAttendee.tenant_id)).where(
        OAMeeting.tenant_id==actor.tenant_id,OAMeeting.state.in_(['SCHEDULED','IN_PROGRESS']),
        OAMeeting.starts_at<payload.ends_at,OAMeeting.ends_at>payload.starts_at,
        OAMeetingAttendee.user_id.in_(ids),OAMeetingAttendee.response!='DECLINED')
    if exclude_id: query=query.where(OAMeeting.id!=exclude_id)
    rows=(await db.execute(query.group_by(OAMeetingAttendee.user_id,OAUser.display_name))).all()
    return [dict(user_id=uid,display_name=name,count=count) for uid,name,count in rows]


async def outcome(db,actor,row,recipients=(),*,external_fields_changed=False):
    return CommandOutcome(result=await view(db,actor,row),recipients=list(recipients),
        recipient_access={uid:('meeting',OAAccessTarget(actor.tenant_id,uid)) for uid in recipients},
        detail=dict(invitation_version=row.invitation_version,revision=row.revision,external_fields_changed=external_fields_changed))


async def execute(db,actor,meeting_id,payload,action,handler):
    actor=await identity(db,actor,'write')
    async def reauthorize():
        row=await db.scalar(select(OAMeeting).where(OAMeeting.tenant_id==actor.tenant_id,
            OAMeeting.id==meeting_id).execution_options(populate_existing=True))
        if row is None:
            if action=='save' and not hasattr(payload,'expected_revision'): return
            raise not_found('会议不存在或不可访问')
        await access(db,actor,meeting_id)
        if action in {'save','publish','cancel','retry'} and row.organizer_id!=actor.user_id: raise denied()
        if action in {'start','end'} and actor.user_id not in {row.organizer_id,row.host_id}: raise denied()
        if action in {'minutes','confirmed'} and not editor(actor,row): raise denied()
    result=await run_command(db,actor,OACommand(kind='meeting.'+action,target_id=meeting_id,
        target_version=str(getattr(payload,'expected_revision',0)),operation_id=payload.operation_id,
        payload=payload.model_dump(mode='json'),resource='meeting',target=OAAccessTarget(actor.tenant_id,actor.user_id),
        reauthorize=reauthorize),handler)
    # Materialize this command's inbox atomically, without running external transports.
    from .oa_notification_service import dispatch
    ids=(await db.scalars(select(OAWorkflowOutbox.id).join(OAWorkflowEvent,
        OAWorkflowEvent.id==OAWorkflowOutbox.event_id).join(OAWorkflowOperation,
        OAWorkflowOperation.id==OAWorkflowEvent.operation_id).where(OAWorkflowOutbox.tenant_id==actor.tenant_id,
        OAWorkflowOperation.actor_id==actor.user_id,OAWorkflowOperation.target_id==meeting_id,
        OAWorkflowOperation.operation_id==payload.operation_id,OAWorkflowOutbox.status=='PENDING'))).all()
    for oid in ids: await dispatch(db,tenant_id=actor.tenant_id,outbox_id=oid)
    return result


async def save(db,actor,payload,meeting_id=None):
    actor=await identity(db,actor,'write')
    creating=meeting_id is None
    meeting_id=meeting_id or str(uuid5(NAMESPACE_URL,actor.tenant_id+':'+actor.user_id+':meeting:'+payload.operation_id))
    if not creating:
        _,before=await access(db,actor,meeting_id)
        if before.organizer_id!=actor.user_id: raise denied()
    async def perform(operation):
        ids=await members(db,actor,payload)
        fields=payload.model_dump(exclude={'operation_id','expected_revision','attendee_ids'})
        external_fields_changed=False
        if creating:
            row=OAMeeting(id=meeting_id,tenant_id=actor.tenant_id,organizer_id=actor.user_id,**fields)
            db.add(row)
            await db.flush()
        else:
            _,row=await access(db,actor,meeting_id,lock=True)
            if row.organizer_id!=actor.user_id: raise denied()
            if row.revision!=payload.expected_revision: raise revision_conflict()
            if row.state not in {'DRAFT','SCHEDULED'}: raise invalid('当前会议不可修改')
            if row.state=='SCHEDULED' and payload.starts_at<=utcnow(): raise invalid('改期后的开始时间必须晚于当前时间')
            external_fields_changed=any(getattr(row,key)!=value for key,value in fields.items()
                if key in {'starts_at','ends_at','location','online_url','video_enabled'})
            for key,value in fields.items(): setattr(row,key,value)
            row.revision+=1
            await db.execute(delete(OAMeetingAttendee).where(OAMeetingAttendee.tenant_id==actor.tenant_id,
                OAMeetingAttendee.meeting_id==row.id))
            if row.state=='SCHEDULED': row.invitation_version+=1
        for uid in ids: db.add(OAMeetingAttendee(tenant_id=actor.tenant_id,meeting_id=row.id,user_id=uid))
        await db.flush()
        return await outcome(db,actor,row,ids if row.state=='SCHEDULED' else [],external_fields_changed=external_fields_changed)
    return await execute(db,actor,meeting_id,payload,'save',perform)


async def transition(db,actor,meeting_id,payload,action):
    actor,row=await access(db,actor,meeting_id)
    if action not in {'publish','start','end','cancel'}: raise invalid('会议操作无效')
    if actor.user_id!=row.organizer_id and not (actor.user_id==row.host_id and action in {'start','end'}): raise denied()
    async def perform(operation):
        _,row=await access(db,actor,meeting_id,lock=True)
        if actor.user_id!=row.organizer_id and not (actor.user_id==row.host_id and action in {'start','end'}): raise denied()
        if row.revision!=payload.expected_revision: raise revision_conflict()
        required={'publish':'DRAFT','start':'SCHEDULED','end':'IN_PROGRESS'}
        if action=='cancel':
            if row.state not in {'DRAFT','SCHEDULED','IN_PROGRESS'}: raise invalid('当前会议不可取消')
            if not payload.reason: raise invalid('请填写取消原因')
            row.cancel_reason=payload.reason
        elif row.state!=required[action]: raise invalid('当前会议状态不可执行此操作')
        if action=='publish':
            if row.starts_at<=utcnow(): raise invalid('会议开始时间必须晚于当前时间')
            from ..schemas.oa_meeting import MeetingFields
            attendee_ids=(await db.scalars(select(OAMeetingAttendee.user_id).where(
                OAMeetingAttendee.tenant_id==actor.tenant_id,OAMeetingAttendee.meeting_id==row.id))).all()
            await members(db,actor,MeetingFields(title=row.title,agenda=row.agenda,starts_at=row.starts_at,
                ends_at=row.ends_at,host_id=row.host_id,recorder_id=row.recorder_id,
                attendee_ids=attendee_ids,location=row.location,online_url=row.online_url,video_enabled=row.video_enabled))
            row.invitation_version+=1
        if row.video_enabled and row.state=='IN_PROGRESS' and action in {'end','cancel'}:
            from .meeting_transcription_service import request_stop
            await request_stop(db,row)
            from .meeting_video_service import close_room
            await close_room(row)
        row.state={'publish':'SCHEDULED','start':'IN_PROGRESS','end':'ENDED','cancel':'CANCELLED'}[action]
        row.revision+=1
        await db.flush()
        recipients=(await db.scalars(select(OAMeetingAttendee.user_id).where(OAMeetingAttendee.tenant_id==actor.tenant_id,
            OAMeetingAttendee.meeting_id==row.id))).all() if row.invitation_version>0 else []
        return await outcome(db,actor,row,recipients)
    return await execute(db,actor,meeting_id,payload,action,perform)


async def reply(db,actor,meeting_id,payload):
    actor,_=await access(db,actor,meeting_id)
    async def perform(operation):
        _,row=await access(db,actor,meeting_id,lock=True)
        if row.invitation_version!=payload.invitation_version or row.revision!=payload.expected_revision: raise revision_conflict()
        if row.state!='SCHEDULED': raise invalid('当前会议不再接受参会反馈')
        attendee=await db.scalar(select(OAMeetingAttendee).where(OAMeetingAttendee.tenant_id==actor.tenant_id,
            OAMeetingAttendee.meeting_id==row.id,OAMeetingAttendee.user_id==actor.user_id).with_for_update())
        if not attendee: raise denied()
        attendee.response,attendee.note,attendee.replied_at=payload.response,payload.note,utcnow()
        await db.flush()
        return await outcome(db,actor,row,[row.organizer_id] if actor.user_id!=row.organizer_id else [])
    return await execute(db,actor,meeting_id,payload,'reply',perform)


async def attach_minutes(db,actor,meeting_id,payload):
    actor,row=await access(db,actor,meeting_id)
    if not editor(actor,row): raise denied()
    async def perform(operation):
        _,row=await access(db,actor,meeting_id,lock=True)
        if not editor(actor,row): raise denied()
        if row.revision!=payload.expected_revision: raise revision_conflict()
        if row.state!='ENDED' or row.minutes_id: raise invalid('会议结束后可创建一份关联纪要')
        from .meeting_service import create_meeting
        from ..schemas.meeting import MeetingInput
        minutes=await create_meeting(db,actor,MeetingInput(title=row.title,content=payload.content,
            idempotency_key='scheduled:'+row.id))
        row.minutes_id=minutes.meeting_id
        row.revision+=1
        await db.flush()
        return await outcome(db,actor,row)
    return await execute(db,actor,meeting_id,payload,'minutes',perform)


async def retry_notifications(db,actor,meeting_id,payload):
    actor,row=await access(db,actor,meeting_id)
    if row.organizer_id!=actor.user_id: raise denied()
    async def perform(operation):
        _,row=await access(db,actor,meeting_id,lock=True)
        if row.organizer_id!=actor.user_id: raise denied()
        if row.revision!=payload.expected_revision: raise revision_conflict()
        from .oa_notification_source import allowed
        notices=(await db.scalars(select(OANotification).where(OANotification.tenant_id==actor.tenant_id,
            OANotification.source['kind'].as_string()=='meeting',
            OANotification.source['object_id'].as_string()==row.id))).all()
        for n in notices:
            if n.source.get('kind')!='meeting' or n.source.get('object_id')!=row.id or not await allowed(db,n): continue
            deliveries=(await db.scalars(select(OANotificationDelivery).where(OANotificationDelivery.tenant_id==actor.tenant_id,
                OANotificationDelivery.notification_id==n.id,OANotificationDelivery.channel.in_(['smtp','wecom']),
                OANotificationDelivery.state=='FAILED').with_for_update())).all()
            for delivery in deliveries:
                delivery.state,delivery.next_attempt_at='PENDING',None
        await db.flush()
        return await outcome(db,actor,row)
    return await execute(db,actor,meeting_id,payload,'retry',perform)


async def notify_minutes_confirmed(db, actor, minutes_id, operation_id):
    row=await db.scalar(select(OAMeeting).where(OAMeeting.tenant_id==actor.tenant_id,OAMeeting.minutes_id==minutes_id))
    if not row: return
    from ..schemas.oa_meeting import MeetingCommand
    payload=MeetingCommand(operation_id=str(uuid5(NAMESPACE_URL,operation_id)),expected_revision=row.revision)
    async def perform(operation):
        _,locked=await access(db,actor,row.id,lock=True)
        if not editor(actor,locked) or locked.state!='ENDED': raise denied()
        recipients=(await db.scalars(select(OAMeetingAttendee.user_id).where(
            OAMeetingAttendee.tenant_id==actor.tenant_id,OAMeetingAttendee.meeting_id==row.id))).all()
        return await outcome(db,actor,locked,recipients)
    return await execute(db,actor,row.id,payload,'confirmed',perform)
