import pytest
from sqlalchemy import select,func

from app.core.errors import AppException
from app.models.oa_reimbursement import OAReimbursementVersion
from app.schemas.oa_leave import OACommand,SubmitLeaveCommand
from app.schemas.oa_workflow import WorkflowSave,PublishWorkflow,DecideNodeCommand
from tests.oa_support import oa_db,seed
from tests.unit.test_oa_money_definition import reimbursement_definition,fields
from tests.api.test_oa_leave_attachments import image_upload


async def setup(db):
    from app.services import oa_workflow_service as workflows
    admin=await seed(db,resources=['workflow','approval','workflow_admin','reimbursement'])
    actor=await seed(db,tenant=admin.tenant_id,department=admin.depts[0],resources=['reimbursement'],scope='self',manager=admin.user_id)
    await db.commit()
    saved=await workflows.save_definition(db,admin,WorkflowSave(operation_id='save',department_id=admin.depts[0],code='reimbursement',name='报销',definition=reimbursement_definition()))
    await workflows.publish_definition(db,admin,saved['id'],PublishWorkflow(operation_id='publish',expected_revision=1))
    await db.commit()
    return admin,actor,saved['id']


async def draft(db,actor,workflow,key='create'):
    from app.schemas.oa_reimbursement import ReimbursementDraftCreate
    from app.services import oa_reimbursement_service as service
    result=await service.create_draft(db,actor,ReimbursementDraftCreate(operation_id=key,workflow_definition_id=workflow,fields=fields()))
    await db.commit()
    return result.result['id']


async def invoice(db,actor,key,monkeypatch):
    from app.services import oa_reimbursement_attachment_service as files
    from app.providers import file_scanner
    async def clean(content): return 'CLEAN'
    monkeypatch.setattr(file_scanner,'scan_bytes',clean)
    result=await files.upload(db,actor,key,image_upload(),operation_id='upload',expected_revision=1)
    await db.commit()
    return result.result['attachment']['id']


async def test_no_invoice_denied_and_authority(oa_db):
    from app.services import oa_reimbursement_service as service
    async with oa_db() as db:
        admin,actor,workflow=await setup(db)
        key=await draft(db,actor,workflow)
        with pytest.raises(AppException): await service.submit(db,actor,key,SubmitLeaveCommand(operation_id='submit',expected_revision=1,requested_submission_version=1))
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(OAReimbursementVersion).where(OAReimbursementVersion.tenant_id==actor.tenant_id))==0
        with pytest.raises(AppException): await service.withdraw(db,admin,key,OACommand(operation_id='foreign',expected_revision=1))
        await db.rollback()
        outsider=await seed(db,tenant=actor.tenant_id,department=actor.depts[0],resources=['reimbursement'],scope='self')
        await db.commit()
        with pytest.raises(AppException): await service.detail(db,outsider,key)


async def test_submission_approval_archive_and_snapshot(oa_db,monkeypatch):
    from app.services import oa_reimbursement_service as service,oa_approval_service as approvals,oa_reimbursement_attachment_service as files
    async with oa_db() as db:
        admin,actor,workflow=await setup(db)
        key=await draft(db,actor,workflow)
        attachment=await invoice(db,actor,key,monkeypatch)
        command=SubmitLeaveCommand(operation_id='submit',expected_revision=2,requested_submission_version=1)
        result=await service.submit(db,actor,key,command)
        await db.commit()
        assert result.result['state']=='IN_REVIEW'
        assert (await service.submit(db,actor,key,command)).replayed
        await db.commit()
        pending=(await approvals.list_items(db,admin,'pending'))[0]
        assert pending['scene']=='reimbursement' and pending['node_key']=='review'
        _,content=await approvals.download(db,admin,pending['node_id'],attachment)
        assert content.startswith(b'\x89PNG')
        with pytest.raises(AppException): await files.rescan(db,actor,key,attachment,operation_id='rescan',expected_revision=3)
        await db.rollback()
        await approvals.decide(db,admin,pending['node_id'],DecideNodeCommand(operation_id='approve',expected_revision=1,action='approve'))
        await db.commit()
        detail=await service.detail(db,actor,key)
        assert detail['state']=='APPROVED' and detail['versions'][0]['amount_minor']==100000
        assert detail['versions'][0]['fields']['amount']=='1000.00'
        archived=await service.archive(db,actor,key,OACommand(operation_id='archive',expected_revision=detail['revision']))
        await db.commit()
        assert archived.result['archived_at'] and archived.result['allowed_actions']==[]


@pytest.mark.parametrize('mode',['all','any'])
async def test_modes_and_frozen_workflow(oa_db,monkeypatch,mode):
    from app.services import oa_reimbursement_service as service,oa_workflow_service as workflows,oa_approval_service as approvals
    async with oa_db() as db:
        admin,actor,workflow=await setup(db)
        second=await seed(db,tenant=actor.tenant_id,department=actor.depts[0],resources=['approval'],scope='self')
        package=reimbursement_definition()
        for node in package['nodes'][1:3]:
            node.update(mode=mode,selector=dict(kind='users',user_ids=[admin.user_id,second.user_id]))
        await workflows.save_definition(db,admin,WorkflowSave(operation_id='mode',department_id=admin.depts[0],code='reimbursement',name='报销',definition=package,expected_revision=2),workflow)
        await workflows.publish_definition(db,admin,workflow,PublishWorkflow(operation_id='mode-pub',expected_revision=3))
        await db.commit()
        key=await draft(db,actor,workflow)
        await invoice(db,actor,key,monkeypatch)
        await service.submit(db,actor,key,SubmitLeaveCommand(operation_id='submit',expected_revision=2,requested_submission_version=1))
        await db.commit()
        snapshot=(await service.detail(db,actor,key))['versions'][0]
        package['nodes'][0]['cases'][0]['value']='1.00'
        await workflows.save_definition(db,admin,WorkflowSave(operation_id='new-rule',department_id=admin.depts[0],code='reimbursement',name='报销',definition=package,expected_revision=4),workflow)
        await workflows.publish_definition(db,admin,workflow,PublishWorkflow(operation_id='rule-pub',expected_revision=5))
        await db.commit()
        pending=(await approvals.list_items(db,admin,'pending'))[0]
        assert pending['node_key']=='review'
        result=await approvals.decide(db,admin,pending['node_id'],DecideNodeCommand(operation_id='approve',expected_revision=1,action='approve'))
        await db.commit()
        assert result.result['state']==('IN_REVIEW' if mode=='all' else 'APPROVED')
        if mode=='all':
            await approvals.decide(db,second,pending['node_id'],DecideNodeCommand(operation_id='second',expected_revision=2,action='approve'))
            await db.commit()
        detail=await service.detail(db,actor,key)
        assert detail['state']=='APPROVED' and detail['versions'][0]==snapshot
        new_key=await draft(db,actor,workflow,'new')
        await invoice(db,actor,new_key,monkeypatch)
        await service.submit(db,actor,new_key,SubmitLeaveCommand(operation_id='submit',expected_revision=2,requested_submission_version=1))
        await db.commit()
        assert (await approvals.list_items(db,admin,'pending'))[0]['node_key']=='high'


@pytest.mark.parametrize('action',['reject','return_for_correction','withdraw'])
async def test_new_round_keeps_history(oa_db,monkeypatch,action):
    from app.services import oa_reimbursement_service as service,oa_approval_service as approvals,oa_reimbursement_attachment_service as files
    from app.schemas.oa_reimbursement import ReimbursementDraftPatch
    async with oa_db() as db:
        admin,actor,workflow=await setup(db)
        key=await draft(db,actor,workflow)
        attachment=await invoice(db,actor,key,monkeypatch)
        await service.submit(db,actor,key,SubmitLeaveCommand(operation_id='submit',expected_revision=2,requested_submission_version=1))
        await db.commit()
        node=(await approvals.list_items(db,admin,'pending'))[0]
        if action=='withdraw': await service.withdraw(db,actor,key,OACommand(operation_id='withdraw',expected_revision=3))
        else:
            await approvals.decide(db,admin,node['node_id'],DecideNodeCommand(operation_id='reject',expected_revision=1,
                action=action,note='补充金额说明',corrections=['amount'] if action=='return_for_correction' else []))
        await db.commit()
        current=await service.detail(db,actor,key)
        with pytest.raises(AppException): await files.rescan(db,actor,key,attachment,operation_id='rescan',expected_revision=current['revision'])
        await db.rollback()
        await service.update_draft(db,actor,key,ReimbursementDraftPatch(operation_id='edit',expected_revision=current['revision'],fields=fields('1000.01',attachment_ids=[attachment])))
        await db.commit()
        updated=await service.detail(db,actor,key)
        await service.submit(db,actor,key,SubmitLeaveCommand(operation_id='resubmit',expected_revision=updated['revision'],requested_submission_version=2))
        await db.commit()
        detail=await service.detail(db,actor,key)
        assert len(detail['versions'])==2
        assert detail['versions'][0]['amount_minor']==100000 and detail['versions'][1]['amount_minor']==100001
        assert detail['versions'][1]['differences']['amount']==dict(before='1000.00',after='1000.01')
        assert (await approvals.list_items(db,admin,'pending'))[0]['node_key']=='high'
        with pytest.raises(AppException): await approvals.node_context(db,admin,node['node_id'])


@pytest.mark.parametrize('status',['PENDING','ERROR','INFECTED'])
async def test_scanner_fail_closed(oa_db,monkeypatch,status):
    from app.services import oa_reimbursement_service as service,oa_reimbursement_attachment_service as files
    from app.providers import file_scanner
    async def scan(content): return status
    monkeypatch.setattr(file_scanner,'scan_bytes',scan)
    async with oa_db() as db:
        _,actor,workflow=await setup(db)
        key=await draft(db,actor,workflow)
        uploaded=await files.upload(db,actor,key,image_upload(),operation_id='upload',expected_revision=1)
        await db.commit()
        assert uploaded.result['attachment']['scan_status']!='CLEAN'
        with pytest.raises(AppException): await service.submit(db,actor,key,SubmitLeaveCommand(operation_id='submit',expected_revision=2,requested_submission_version=1))


async def test_invoice_scope_and_tamper(oa_db,monkeypatch):
    from app.services import oa_reimbursement_service as service,oa_reimbursement_attachment_service as files
    from app.models.oa_reimbursement import OAReimbursementAttachment
    async with oa_db() as db:
        _,actor,workflow=await setup(db)
        key=await draft(db,actor,workflow)
        attachment=await invoice(db,actor,key,monkeypatch)
        other=await draft(db,actor,workflow,'other')
        with pytest.raises(AppException): await files.preflight(db,actor,other,[attachment])
        await db.rollback()
        foreign=await seed(db,resources=['reimbursement'])
        await db.commit()
        with pytest.raises(AppException): await files.download(db,foreign,key,attachment)
        await db.rollback()
        item=await db.get(OAReimbursementAttachment,attachment)
        path=files.storage_path(item)
        path.write_bytes(b'changed bytes')
        with pytest.raises(AppException): await service.submit(db,actor,key,SubmitLeaveCommand(operation_id='submit',expected_revision=2,requested_submission_version=1))
        await db.rollback()
        path.unlink()
        with pytest.raises(AppException): await files.download(db,actor,key,attachment)


@pytest.mark.parametrize('failure',['event','outbox'])
async def test_submit_rollback(oa_db,monkeypatch,failure):
    from app.services import oa_reimbursement_service as service
    from app.models.oa_reimbursement import OAReimbursement
    from app.models.oa_workflow import OAWorkflowOperation,OAWorkflowEvent,OAWorkflowOutbox,OAWorkflowInstance
    async with oa_db() as db:
        _,actor,workflow=await setup(db)
        key=await draft(db,actor,workflow)
        await invoice(db,actor,key,monkeypatch)
        flush=db.flush
        async def fail(*args,**kwargs):
            model=OAWorkflowEvent if failure=='event' else OAWorkflowOutbox
            if any(isinstance(item,model) for item in db.new): raise RuntimeError('injected '+failure)
            return await flush(*args,**kwargs)
        monkeypatch.setattr(db,'flush',fail)
        with pytest.raises(RuntimeError,match='injected'): await service.submit(db,actor,key,SubmitLeaveCommand(operation_id='fail',expected_revision=2,requested_submission_version=1))
        monkeypatch.setattr(db,'flush',flush)
        await db.commit()
        row=await db.get(OAReimbursement,key,populate_existing=True)
        assert (row.state,row.revision,row.submission_version)==('DRAFT',2,0)
        for model in [OAReimbursementVersion,OAWorkflowInstance]:
            assert await db.scalar(select(func.count()).select_from(model).where(model.tenant_id==actor.tenant_id))==0
        assert await db.scalar(select(func.count()).select_from(OAWorkflowOperation).where(OAWorkflowOperation.tenant_id==actor.tenant_id,OAWorkflowOperation.operation_id=='fail'))==0


async def test_ai_off_http_and_scene_permission(oa_db):
    from fastapi import FastAPI
    from httpx import ASGITransport,AsyncClient
    from starlette.requests import Request
    from app.api.routers import oa_reimbursements
    from app.api.deps import get_current_user
    from app.core.context import set_current_user
    from app.core.config import get_settings
    from app.db.session import get_db
    async with oa_db() as db:
        _,actor,workflow=await setup(db)
        prefix=get_settings().api_prefix
        set_current_user(actor)
        try:
            request=Request(dict(type='http',method='GET',path=prefix+'/oa/workflows',query_string=b'available=true&scene=reimbursement',headers=[]))
            assert (await get_current_user(request,db)).user_id==actor.user_id
            request=Request(dict(type='http',method='POST',path=prefix+'/oa/reimbursements',query_string=b'',headers=[]))
            assert (await get_current_user(request,db)).user_id==actor.user_id
            app=FastAPI()
            app.include_router(oa_reimbursements.router,prefix=prefix)
            async def database(): yield db
            app.dependency_overrides[get_db]=database
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                response=await client.post(prefix+'/oa/reimbursements',json=dict(operation_id='http',workflow_definition_id=workflow,fields=fields().model_dump(mode='json')))
                assert response.status_code==200
                key=response.json()['data']['result']['id']
                response=await client.get(prefix+'/oa/reimbursements/'+key)
                assert response.status_code==200 and response.json()['data']['state']=='DRAFT'
        finally: set_current_user(None)


async def test_scene_is_fixed_and_no_automatic_grants(oa_db):
    from app.services import oa_workflow_service as workflows,oa_reimbursement_service as service
    from tests.unit.test_oa_workflow_definition import definition
    from app.services.organization_service import RESOURCES,BUSINESS_RESOURCES
    async with oa_db() as db:
        admin,actor,workflow=await setup(db)
        assert 'reimbursement' in RESOURCES and 'reimbursement' not in BUSINESS_RESOURCES
        assert [row['id'] for row in await workflows.list_definitions(db,actor,available=True,scene='reimbursement')]==[workflow]
        with pytest.raises(AppException): await workflows.list_definitions(db,actor,available=True)
        await db.rollback()
        with pytest.raises(AppException):
            await workflows.save_definition(db,admin,WorkflowSave(operation_id='wrong-scene',expected_revision=2,department_id=admin.depts[0],code='reimbursement',name='错误',definition=definition()),workflow)
        await db.rollback()
        with pytest.raises(AppException): await workflows.current_version(db,actor,workflow)
        await db.rollback()
        user=await seed(db,tenant=actor.tenant_id,department=actor.depts[0],resources=['leave'])
        await db.commit()
        from app.schemas.oa_reimbursement import ReimbursementDraftCreate
        with pytest.raises(AppException):
            await service.create_draft(db,user,ReimbursementDraftCreate(operation_id='forbidden',workflow_definition_id=workflow,fields=fields()))


async def test_missing_manager_pauses_and_handoff_recovers(oa_db,monkeypatch):
    from app.models.identity import OAMembership
    from app.services import oa_reimbursement_service as service,oa_handoff_service as handoff,oa_approval_service as approvals
    from app.schemas.oa_workflow import RouteResumeCommand,SeatHandoffCommand
    async with oa_db() as db:
        admin,actor,workflow=await setup(db)
        second=await seed(db,tenant=actor.tenant_id,department=actor.depts[0],resources=['approval'],scope='self')
        member=await db.get(OAMembership,(actor.tenant_id,actor.user_id))
        member.manager_id=None
        await db.commit()
        key=await draft(db,actor,workflow)
        attachment=await invoice(db,actor,key,monkeypatch)
        result=await service.submit(db,actor,key,SubmitLeaveCommand(operation_id='submit',expected_revision=2,requested_submission_version=1))
        await db.commit()
        assert result.result['state']=='PAUSED'
        instance=next(row for row in await handoff.list_instances(db,admin) if row['object_id']==key)
        seat=instance['nodes'][0]['seats'][0]
        await handoff.resume(db,admin,instance['instance_id'],RouteResumeCommand(operation_id='resume',expected_revision=instance['revision'],
            reason='补充明确处理人',replacements=[dict(seat_id=seat['id'],target_user_id=admin.user_id)]))
        await db.commit()
        node=(await approvals.list_items(db,admin,'pending'))[0]
        # Explicit recovery substitution is not chained by another handoff.
        with pytest.raises(AppException): await handoff.transfer(db,admin,seat['id'],SeatHandoffCommand(operation_id='chain',expected_revision=node['revision'],target_user_id=second.user_id,reason='再次转交'))
        await db.rollback()
        await approvals.decide(db,admin,node['node_id'],DecideNodeCommand(operation_id='approve',expected_revision=node['revision'],action='approve'))
        await db.commit()
        assert (await service.detail(db,actor,key))['state']=='APPROVED'


async def test_revocation_blocks_download_and_idempotent_replay(oa_db,monkeypatch):
    from sqlalchemy import delete
    from app.models.identity import OAUserRole,OARolePermission
    from app.services import oa_reimbursement_service as service,oa_reimbursement_attachment_service as files
    async with oa_db() as db:
        _,actor,workflow=await setup(db)
        key=await draft(db,actor,workflow)
        attachment=await invoice(db,actor,key,monkeypatch)
        command=SubmitLeaveCommand(operation_id='submit',expected_revision=2,requested_submission_version=1)
        await service.submit(db,actor,key,command)
        await db.commit()
        roles=select(OAUserRole.role_id).where(OAUserRole.tenant_id==actor.tenant_id,OAUserRole.user_id==actor.user_id)
        await db.execute(delete(OARolePermission).where(OARolePermission.tenant_id==actor.tenant_id,OARolePermission.role_id.in_(roles)))
        await db.commit()
        for call in [lambda:files.download(db,actor,key,attachment),lambda:service.submit(db,actor,key,command),lambda:service.list_reimbursements(db,actor)]:
            with pytest.raises(AppException): await call()
            await db.rollback()


async def test_parallel_submit_has_one_snapshot(oa_db,monkeypatch):
    import asyncio
    from app.services import oa_reimbursement_service as service
    async with oa_db() as db:
        _,actor,workflow=await setup(db)
        key=await draft(db,actor,workflow)
        await invoice(db,actor,key,monkeypatch)
    command=SubmitLeaveCommand(operation_id='parallel',expected_revision=2,requested_submission_version=1)
    async def submit():
        async with oa_db() as db:
            result=await service.submit(db,actor,key,command)
            await db.commit()
            return result
    results=await asyncio.gather(submit(),submit())
    assert sorted(row.replayed for row in results)==[False,True]
    async with oa_db() as db:
        assert await db.scalar(select(func.count()).select_from(OAReimbursementVersion).where(OAReimbursementVersion.reimbursement_id==key))==1
