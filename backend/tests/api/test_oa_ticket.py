from datetime import datetime,timedelta,timezone

import pytest
from sqlalchemy import select,func,delete
from app.core.errors import AppException
from tests.oa_support import oa_db,seed


async def setup(db):
    handler=await seed(db,resources=['ticket_handle','ticket_admin'])
    owner=await seed(db,tenant=handler.tenant_id,department=handler.depts[0],resources=['ticket'],scope='self')
    await db.commit()
    return handler,owner


def proposal(key='create',**values):
    from app.schemas.oa_ticket import FormalTicketProposal
    return FormalTicketProposal(operation_id=key,category='设备',priority='medium',impact='个人',summary='电脑无法启动',**values)


async def create(db,owner,key='create'):
    from app.services import oa_ticket_service as service
    command=proposal(key)
    confirmation=await service.prepare(db,owner,command)
    await db.commit()
    result=await service.create_or_merge(db,owner,command,confirmation_id=confirmation['confirmation_id'])
    await db.commit()
    return result.result,command,confirmation


async def test_create_confirm_replay_result_and_legacy_isolation(oa_db):
    from app.services import oa_ticket_service as service
    from app.models.oa_ticket import OATicket
    from app.models.oa_bridge import OABridgeResult,OABridgeConfirmation
    from app.models.ticket_record import TicketRecord
    async with oa_db() as db:
        _,owner=await setup(db)
        original,command,confirmation=await create(db,owner)
        assert original['state']=='OPEN' and original['assignee_id'] is None
        assert original['assignment_error'] and original['revision']==1
        replay=await service.create_or_merge(db,owner,command,confirmation_id=confirmation['confirmation_id'])
        await db.commit()
        assert replay.replayed and replay.result==original
        assert (await service.get_result(db,owner,'create'))['id']==original['id']
        assert await db.scalar(select(func.count()).select_from(OATicket).where(OATicket.tenant_id==owner.tenant_id))==1
        assert await db.scalar(select(func.count()).select_from(OABridgeResult).where(OABridgeResult.tenant_id==owner.tenant_id))==1
        assert (await db.get(OABridgeConfirmation,confirmation['confirmation_id'])).consumed_operation_id
        assert await db.scalar(select(func.count()).select_from(TicketRecord).where(TicketRecord.tenant_id==owner.tenant_id))==0


async def test_forged_other_actor_expired_and_altered_confirmation(oa_db):
    from app.services import oa_ticket_service as service
    from app.models.oa_bridge import OABridgeConfirmation
    async with oa_db() as db:
        _,owner=await setup(db)
        other=await seed(db,tenant=owner.tenant_id,department=owner.depts[0],resources=['ticket'],scope='self')
        command=proposal()
        confirmation=await service.prepare(db,owner,command)
        await db.commit()
        for actor,payload,token in [(owner,command,'fake'),(other,command,confirmation['confirmation_id']),
                                   (owner,command.model_copy(update={'summary':'修改内容'}),confirmation['confirmation_id'])]:
            with pytest.raises(AppException): await service.create_or_merge(db,actor,payload,confirmation_id=token)
            await db.rollback()
        row=await db.get(OABridgeConfirmation,confirmation['confirmation_id'])
        row.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        await db.commit()
        with pytest.raises(AppException): await service.create_or_merge(db,owner,command,confirmation_id=row.id)


async def test_merge_target_version_hash_and_history_replay(oa_db):
    from app.services import oa_ticket_service as service
    from app.schemas.oa_ticket import TicketHandleCommand
    async with oa_db() as db:
        handler,owner=await setup(db)
        first,_,_=await create(db,owner,'first')
        second,_,_=await create(db,owner,'second')
        command=proposal('merge',merge_ticket_id=first['id'],expected_revision=1)
        confirm=await service.prepare(db,owner,command)
        assert any(row['id']==first['id'] for row in confirm['duplicate_candidates'])
        result=await service.create_or_merge(db,owner,command,confirmation_id=confirm['confirmation_id'])
        await db.commit()
        assert result.result['merged'] and result.result['revision']==2
        changed=proposal('merge',merge_ticket_id=second['id'],expected_revision=1)
        changed_confirm=await service.prepare(db,owner,changed)
        await db.commit()
        with pytest.raises(AppException) as error: await service.create_or_merge(db,owner,changed,confirmation_id=changed_confirm['confirmation_id'])
        assert error.value.http_status==409
        await db.rollback()
        await service.handle(db,handler,first['id'],TicketHandleCommand(operation_id='claim',expected_revision=2,action='claim'))
        await db.commit()
        replay=await service.create_or_merge(db,owner,command,confirmation_id=confirm['confirmation_id'])
        assert replay.replayed and replay.result==result.result
        detail=await service.detail(db,owner,first['id'])
        assert len(detail['merged_requests'])==1 and detail['revision']==3


async def test_stale_target_and_nonowner_merge_rejected(oa_db):
    from app.services import oa_ticket_service as service
    from app.schemas.oa_ticket import TicketHandleCommand
    async with oa_db() as db:
        handler,owner=await setup(db)
        original,_,_=await create(db,owner)
        command=proposal('merge',merge_ticket_id=original['id'],expected_revision=1)
        confirm=await service.prepare(db,owner,command)
        await db.commit()
        await service.handle(db,handler,original['id'],TicketHandleCommand(operation_id='claim',expected_revision=1,action='claim'))
        await db.commit()
        with pytest.raises(AppException): await service.create_or_merge(db,owner,command,confirmation_id=confirm['confirmation_id'])
        await db.rollback()
        foreign=await seed(db,tenant=owner.tenant_id,department=owner.depts[0],resources=['ticket'])
        await db.commit()
        with pytest.raises(AppException): await service.prepare(db,foreign,proposal('foreign',merge_ticket_id=original['id'],expected_revision=2))


async def test_assignment_versions_handle_feedback_and_reopen(oa_db):
    from app.services import oa_ticket_service as service
    from app.schemas.oa_ticket import TicketRuleSave,TicketHandleCommand,TicketFeedbackCommand
    async with oa_db() as db:
        handler,owner=await setup(db)
        rule=TicketRuleSave(operation_id='rule1',department_id=handler.depts[0],code='device',category='设备',
            impact='*',queue='设备支持',assignee_id=handler.user_id,priority=10)
        one=await service.save_rule(db,handler,rule)
        await db.commit()
        original,_,_=await create(db,owner)
        assert original['assignee_id']==handler.user_id and original['assignment_rule_version']==1
        assert original['state']=='OPEN'
        two=await service.save_rule(db,handler,rule.model_copy(update={'operation_id':'rule2','queue':'综合支持','expected_version':1}))
        await db.commit()
        assert two.result['version']==2 and one.result['version']==1
        assert (await service.detail(db,owner,original['id']))['queue']=='设备支持'
        started=await service.handle(db,handler,original['id'],TicketHandleCommand(operation_id='start',expected_revision=1,action='start'))
        await db.commit()
        resolved=await service.handle(db,handler,original['id'],TicketHandleCommand(operation_id='resolve',expected_revision=2,action='resolve',note='已维修'))
        await db.commit()
        assert started.result['state']=='IN_PROGRESS' and resolved.result['state']=='RESOLVED'
        negative=TicketFeedbackCommand(operation_id='negative',expected_revision=3,resolved=False,comment='仍不能开机')
        reopened=await service.feedback(db,owner,original['id'],negative)
        await db.commit()
        assert reopened.result['state']=='OPEN'
        assert (await service.feedback(db,owner,original['id'],negative)).replayed
        await db.commit()
        await service.handle(db,handler,original['id'],TicketHandleCommand(operation_id='resolve2',expected_revision=4,action='resolve',note='再次维修'))
        await db.commit()
        closed=await service.feedback(db,owner,original['id'],TicketFeedbackCommand(operation_id='positive',expected_revision=5,resolved=True,comment='已恢复'))
        await db.commit()
        assert closed.result['state']=='CLOSED'
        assert len((await service.detail(db,owner,original['id']))['feedback'])==2


async def test_scope_revocation_and_invalid_assignee(oa_db):
    from app.services import oa_ticket_service as service
    from app.schemas.oa_ticket import TicketHandleCommand,TicketRuleSave
    from app.models.identity import OAUserRole,OARolePermission
    async with oa_db() as db:
        handler,owner=await setup(db)
        original,command,confirmation=await create(db,owner)
        outsider=await seed(db,resources=['ticket','ticket_handle','ticket_admin'])
        fake_admin=await seed(db,tenant=owner.tenant_id,department=owner.depts[0],resources=[])
        fake_admin.roles=['admin']
        await db.commit()
        for actor in [outsider,fake_admin]:
            with pytest.raises(AppException): await service.detail(db,actor,original['id'])
            await db.rollback()
            with pytest.raises(AppException): await service.handle(db,actor,original['id'],TicketHandleCommand(operation_id='foreign',expected_revision=1,action='claim'))
            await db.rollback()
        with pytest.raises(AppException): await service.save_rule(db,handler,TicketRuleSave(operation_id='bad',department_id=handler.depts[0],code='bad',queue='支持',assignee_id=outsider.user_id))
        await db.rollback()
        roles=select(OAUserRole.role_id).where(OAUserRole.tenant_id==owner.tenant_id,OAUserRole.user_id==owner.user_id)
        await db.execute(delete(OARolePermission).where(OARolePermission.tenant_id==owner.tenant_id,OARolePermission.role_id.in_(roles)))
        await db.commit()
        for call in [lambda:service.list_tickets(db,owner),lambda:service.get_result(db,owner,'create'),
                     lambda:service.create_or_merge(db,owner,command,confirmation_id=confirmation['confirmation_id'])]:
            with pytest.raises(AppException): await call()
            await db.rollback()


@pytest.mark.parametrize('fault',['event','bridge'])
async def test_confirmation_domain_result_rollback(oa_db,monkeypatch,fault):
    from app.services import oa_ticket_service as service,oa_command_service as commands,oa_confirmation_service as confirmations
    from app.models.oa_ticket import OATicket
    from app.models.oa_bridge import OABridgeConfirmation,OABridgeResult
    async with oa_db() as db:
        _,owner=await setup(db)
        command=proposal()
        confirmation=await service.prepare(db,owner,command)
        await db.commit()
        async def fail(*args,**kwargs): raise RuntimeError('injected')
        with monkeypatch.context() as patch:
            patch.setattr(commands if fault=='event' else confirmations,'persist_events' if fault=='event' else 'record_result',fail)
            with pytest.raises(RuntimeError): await service.create_or_merge(db,owner,command,confirmation_id=confirmation['confirmation_id'])
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(OATicket).where(OATicket.tenant_id==owner.tenant_id))==0
        assert await db.scalar(select(func.count()).select_from(OABridgeResult).where(OABridgeResult.tenant_id==owner.tenant_id))==0
        assert (await db.get(OABridgeConfirmation,confirmation['confirmation_id'])).consumed_operation_id is None
        assert not (await service.create_or_merge(db,owner,command,confirmation_id=confirmation['confirmation_id'])).replayed
        await db.commit()


async def test_thread_binding_is_server_owned(oa_db):
    from uuid import uuid4
    from app.models.agent_thread import AgentThread
    from app.services import oa_ticket_service as service
    async with oa_db() as db:
        _,owner=await setup(db)
        stranger=await seed(db,tenant=owner.tenant_id,department=owner.depts[0],resources=['ticket'],scope='self')
        thread=AgentThread(id=uuid4(),tenant_id=owner.tenant_id,user_id=owner.user_id,scene='ticket',status='DRAFT')
        db.add(thread)
        await db.commit()
        command=proposal(thread_id=str(thread.id))
        with pytest.raises(AppException): await service.prepare(db,stranger,command)
        await db.rollback()
        confirmation=await service.prepare(db,owner,command)
        await db.commit()
        with pytest.raises(AppException): await service.create_or_merge(db,owner,command.model_copy(update={'thread_id':None}),confirmation_id=confirmation['confirmation_id'])


async def test_negative_feedback_without_handler_stays_manual(oa_db):
    from app.services import oa_ticket_service as service
    from app.schemas.oa_ticket import TicketHandleCommand,TicketFeedbackCommand
    from app.models.identity import OAUser
    from app.models.human_queue_item import HumanQueueItem
    async with oa_db() as db:
        handler,owner=await setup(db)
        original,_,_=await create(db,owner)
        await service.handle(db,handler,original['id'],TicketHandleCommand(operation_id='claim',expected_revision=1,action='claim'))
        await service.handle(db,handler,original['id'],TicketHandleCommand(operation_id='resolve',expected_revision=2,action='resolve',note='完成'))
        await db.commit()
    async with oa_db() as db:
        user=await db.get(OAUser,handler.user_id)
        user.status='disabled'
        await db.flush()
        await db.commit()
    async with oa_db() as db:
        reopened=await service.feedback(db,owner,original['id'],TicketFeedbackCommand(operation_id='negative',expected_revision=3,resolved=False,comment='未解决'))
        await db.commit()
        assert reopened.result['state']=='OPEN' and reopened.result['assignee_id'] is None
        assert reopened.result['assignment_error']
        assert await db.scalar(select(func.count()).select_from(HumanQueueItem).where(HumanQueueItem.tenant_id==owner.tenant_id))==0


async def test_http_manual_ai_off_and_permissions(oa_db):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from httpx import ASGITransport,AsyncClient
    from app.api.routers import oa_tickets
    from app.core.context import set_current_user
    from app.core.config import get_settings
    from app.db.session import get_db
    async with oa_db() as db:
        handler,owner=await setup(db)
        app=FastAPI()
        prefix=get_settings().api_prefix
        app.include_router(oa_tickets.router,prefix=prefix)
        async def database(): yield db
        app.dependency_overrides[get_db]=database
        @app.exception_handler(AppException)
        async def error(request,exc): return JSONResponse({'message':exc.message},status_code=exc.http_status)
        set_current_user(owner)
        try:
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                command=proposal('http').model_dump(mode='json')
                response=await client.post(prefix+'/oa/tickets/prepare',json=command)
                assert response.status_code==200
                token=response.json()['data']['confirmation_id']
                response=await client.post(prefix+'/oa/tickets',json={**command,'confirmation_id':token})
                assert response.status_code==200
                ticket=response.json()['data']['result']
                assert (await client.get(prefix+'/oa/tickets/'+ticket['id'])).status_code==200
                assert (await client.get(prefix+'/oa/tickets/results/http')).json()['data']['id']==ticket['id']
                assert (await client.get(prefix+'/oa/tickets?handling=true')).status_code==403
                assert (await client.get(prefix+'/oa/tickets/rules',params={'department_id':owner.depts[0]})).status_code==403
                set_current_user(handler)
                assert (await client.get(prefix+'/oa/tickets?handling=true')).status_code==200
                response=await client.post(prefix+'/oa/tickets/'+ticket['id']+'/handle',json=dict(operation_id='claim-http',expected_revision=1,action='claim'))
                assert response.status_code==200 and response.json()['data']['result']['assignee_id']==handler.user_id
        finally: set_current_user(None)


async def test_reassign_current_scope_and_resolution_authority(oa_db):
    from app.services import oa_ticket_service as service
    from app.schemas.oa_ticket import TicketHandleCommand
    async with oa_db() as db:
        handler,owner=await setup(db)
        second=await seed(db,tenant=owner.tenant_id,department=owner.depts[0],resources=['ticket_handle'])
        outsider=await seed(db,tenant=owner.tenant_id,resources=['ticket_handle'])
        await db.commit()
        original,_,_=await create(db,owner)
        await service.handle(db,handler,original['id'],TicketHandleCommand(operation_id='claim',expected_revision=1,action='claim'))
        await db.commit()
        for actor,action,person in [(second,'resolve',None),(handler,'reassign',outsider.user_id)]:
            with pytest.raises(AppException): await service.handle(db,actor,original['id'],TicketHandleCommand(operation_id='invalid',expected_revision=2,action=action,target_user_id=person,note='说明'))
            await db.rollback()
        await service.handle(db,handler,original['id'],TicketHandleCommand(operation_id='reassign',expected_revision=2,action='reassign',target_user_id=second.user_id,note='请协助'))
        await db.commit()
        with pytest.raises(AppException): await service.handle(db,handler,original['id'],TicketHandleCommand(operation_id='old-person',expected_revision=3,action='resolve',note='完成'))
        await db.rollback()
        assert (await service.handle(db,second,original['id'],TicketHandleCommand(operation_id='resolve',expected_revision=3,action='resolve',note='完成'))).result['state']=='RESOLVED'


async def test_terminal_merge_and_outbox_fault_are_atomic(oa_db,monkeypatch):
    from app.services import oa_ticket_service as service,oa_command_service as commands
    from app.schemas.oa_ticket import TicketHandleCommand,TicketRuleSave
    from app.models.oa_bridge import OABridgeConfirmation
    from app.models.oa_workflow import OAWorkflowOutbox
    async with oa_db() as db:
        handler,owner=await setup(db)
        await service.save_rule(db,handler,TicketRuleSave(operation_id='rule',department_id=handler.depts[0],code='default',queue='支持',assignee_id=handler.user_id))
        await db.commit()
        command=proposal('fault')
        confirmation=await service.prepare(db,owner,command)
        await db.commit()
        original_events=commands.persist_events
        async def fail_after_outbox(*args):
            await original_events(*args)
            assert await db.scalar(select(func.count()).select_from(OAWorkflowOutbox).where(OAWorkflowOutbox.tenant_id==owner.tenant_id))==1
            raise RuntimeError('after outbox')
        with monkeypatch.context() as patch:
            patch.setattr(commands,'persist_events',fail_after_outbox)
            with pytest.raises(RuntimeError): await service.create_or_merge(db,owner,command,confirmation_id=confirmation['confirmation_id'])
        await db.rollback()
        assert (await db.get(OABridgeConfirmation,confirmation['confirmation_id'])).consumed_operation_id is None
        assert await db.scalar(select(func.count()).select_from(OAWorkflowOutbox).where(OAWorkflowOutbox.tenant_id==owner.tenant_id))==0
        ticket=(await service.create_or_merge(db,owner,command,confirmation_id=confirmation['confirmation_id'])).result
        await db.commit()
        await service.handle(db,handler,ticket['id'],TicketHandleCommand(operation_id='resolve',expected_revision=1,action='resolve',note='完成'))
        await db.commit()
        with pytest.raises(AppException): await service.prepare(db,owner,proposal('terminal',merge_ticket_id=ticket['id'],expected_revision=2))


async def test_fresh_token_cannot_replay_consumed_confirmation(oa_db):
    from app.services import oa_ticket_service as service
    async with oa_db() as db:
        _,owner=await setup(db)
        _,command,_=await create(db,owner)
        other_token=await service.prepare(db,owner,command)
        await db.commit()
        with pytest.raises(AppException): await service.create_or_merge(db,owner,command,confirmation_id=other_token['confirmation_id'])


async def test_assignment_disabled_new_version_does_not_rewrite_old(oa_db):
    from app.services import oa_ticket_service as service
    from app.schemas.oa_ticket import TicketRuleSave
    from app.models.oa_ticket import OATicketAssignmentRule
    async with oa_db() as db:
        handler,owner=await setup(db)
        rule=TicketRuleSave(operation_id='one',department_id=handler.depts[0],code='default',queue='支持',assignee_id=handler.user_id)
        await service.save_rule(db,handler,rule)
        await db.commit()
        first,_,_=await create(db,owner,'first')
        await service.save_rule(db,handler,rule.model_copy(update={'operation_id':'two','expected_version':1,'enabled':False}))
        await db.commit()
        second,_,_=await create(db,owner,'second')
        assert first['assignment_rule_version']==1 and second['assignee_id'] is None
        assert (await db.scalar(select(OATicketAssignmentRule).where(OATicketAssignmentRule.tenant_id==owner.tenant_id,OATicketAssignmentRule.version==1))).enabled
        assert all(row['version']==2 for row in await service.list_rules(db,handler,handler.depts[0]))
