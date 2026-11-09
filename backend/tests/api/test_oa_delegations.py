from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select, func
from app.core.errors import AppException
from app.models.identity import OAUser, OAMembership, OARolePermission, OAUserRole
from app.models.oa_delegation import OAApprovalDelegation
from app.models.oa_workflow import OAWorkflowSeat, OAWorkflowEvent
from app.models.oa_leave import OALeaveBalance
from app.schemas.oa_delegation import DelegationCreate, DelegationRevoke
from app.schemas.oa_workflow import DecideNodeCommand
from app.services import oa_delegation_service as service, oa_approval_service as approvals, oa_work_item_service
from app.services.identity_service import utcnow
from tests.oa_support import oa_db, seed
from tests.api.test_oa_approval_modes import submitted


def command(delegate, **changes):
    now=utcnow()
    return DelegationCreate(**(dict(operation_id=uuid4().hex, delegate_id=delegate.user_id, scene='leave',
        starts_at=now-timedelta(minutes=1), ends_at=now+timedelta(days=1), reason='出差期间委托') | changes))


async def test_delegate_real_approval_once_attributed_and_history_survives_revoke(oa_db):
    async with oa_db() as db:
        owner,delegate,_,applicant,_=await submitted(db)
        payload=command(delegate)
        outcome=await service.create(db,owner,payload)
        await db.commit()
        assert (await service.create(db,owner,payload)).replayed
        await db.commit()
        assert len(await service.list_items(db,delegate))==1
        pending=await approvals.list_items(db,delegate,'pending')
        assert len(pending)==1 and pending[0]['is_delegated']
        node=pending[0]['node_id']
        assert (await approvals.node_context(db,delegate,node))['is_delegated']
        assert (await oa_work_item_service.pending(db,delegate))['items'][0]['title'].startswith('代批')
        decision=DecideNodeCommand(operation_id='delegated-decision', expected_revision=1, action='approve')
        result=await approvals.decide(db,delegate,node,decision)
        await db.commit()
        assert result.result['state']=='APPROVED'
        seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node))
        assert seat.effective_user_id==owner.user_id and seat.decided_by==delegate.user_id
        assert seat.decision_delegation_id==outcome.result['id']
        event=await db.scalar(select(OAWorkflowEvent).where(OAWorkflowEvent.target_id==node, OAWorkflowEvent.action=='approval.decide'))
        assert event.actor_id==delegate.user_id and event.detail['delegated_for_id']==owner.user_id
        balance=await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==applicant.user_id))
        assert (balance.used,balance.reserved)==(1,0)
        revoke=DelegationRevoke(operation_id='revoke',expected_revision=1)
        await service.revoke(db,owner,outcome.result['id'],revoke)
        await db.commit()
        assert (await service.revoke(db,owner,outcome.result['id'],revoke)).replayed
        assert (await approvals.decide(db,delegate,node,decision)).replayed
        assert len(await approvals.list_items(db,delegate,'done'))==1
        assert not await approvals.list_items(db,delegate,'pending')
        assert await db.scalar(select(func.count()).select_from(OAWorkflowEvent).where(
            OAWorkflowEvent.target_id==node,OAWorkflowEvent.action=='approval.decide'))==1


@pytest.mark.parametrize('boundary',['before','start','end','revoked','disabled','moved','permission','owner_disabled','owner_moved'])
async def test_live_boundaries_remove_read_write_and_pending(oa_db,monkeypatch,boundary):
    async with oa_db() as db:
        owner,delegate,_,_,_=await submitted(db)
        now=utcnow()
        payload=command(delegate,starts_at=now+timedelta(hours=1),ends_at=now+timedelta(hours=2))
        row=(await service.create(db,owner,payload)).result
        await db.commit()
        clock=payload.starts_at if boundary!='before' else payload.starts_at-timedelta(microseconds=1)
        if boundary=='end': clock=payload.ends_at
        monkeypatch.setattr(service,'utcnow',lambda:clock)
        monkeypatch.setattr(approvals,'utcnow',lambda:clock)
        node=(await approvals.list_items(db,owner,'pending'))[0]['node_id']
        if boundary=='revoked':
            await service.revoke(db,owner,row['id'],DelegationRevoke(operation_id='revoke',expected_revision=1))
        elif boundary in {'disabled','owner_disabled'}:
            async with oa_db() as admin_db:
                user=await admin_db.get(OAUser,delegate.user_id if boundary=='disabled' else owner.user_id)
                user.status='disabled'
                await admin_db.commit()
        elif boundary in {'moved','owner_moved'}:
            other=await seed(db,tenant=owner.tenant_id)
            membership=await db.get(OAMembership,(owner.tenant_id,delegate.user_id if boundary=='moved' else owner.user_id))
            membership.department_id=other.depts[0]
        elif boundary=='permission':
            role=await db.scalar(select(OAUserRole.role_id).where(OAUserRole.user_id==delegate.user_id))
            for link in (await db.scalars(select(OARolePermission).where(OARolePermission.role_id==role))).all(): await db.delete(link)
        if boundary not in {'disabled','owner_disabled'}:
            await db.commit()
        if boundary=='start':
            assert len(await approvals.list_items(db,delegate,'pending'))==1
            assert (await approvals.node_context(db,delegate,node))['is_delegated']
            return
        if boundary in {'disabled','permission'}:
            with pytest.raises(AppException): await approvals.list_items(db,delegate,'pending')
            await db.rollback()
        else:
            assert not await approvals.list_items(db,delegate,'pending')
        with pytest.raises(AppException): await approvals.node_context(db,delegate,node)
        await db.rollback()
        with pytest.raises(AppException):
            await approvals.decide(db,delegate,node,DecideNodeCommand(operation_id='forbidden',expected_revision=1,action='approve'))


async def test_forbids_self_cross_tenant_scope_chain_overlap_and_other_revoke(oa_db):
    async with oa_db() as db:
        owner,delegate,third,applicant,_=await submitted(db)
        outsider=await seed(db,resources=['approval'])
        no_permission=await seed(db,tenant=owner.tenant_id,department=owner.depts[0])
        await db.commit()
        for target in (owner,outsider,no_permission):
            with pytest.raises(AppException): await service.create(db,owner,command(target))
            await db.rollback()
        saved=(await service.create(db,owner,command(delegate))).result
        await db.commit()
        for source,target in ((owner,third),(delegate,third),(third,owner),(third,delegate)):
            with pytest.raises(AppException): await service.create(db,source,command(target))
            await db.rollback()
        with pytest.raises(AppException):
            await service.revoke(db,delegate,saved['id'],DelegationRevoke(operation_id='no',expected_revision=1))
        await db.rollback()
        assert not await service.list_items(db,outsider)
        with pytest.raises(AppException): await service.list_items(db,applicant)
        assert outsider.user_id not in [r['id'] for r in await service.candidates(db,owner)]


@pytest.mark.parametrize('mode',['all','any'])
async def test_delegate_cannot_fill_another_seat_or_self_approve(oa_db,mode):
    async with oa_db() as db:
        owner,delegate,_,applicant,_=await submitted(db,mode=mode)
        await service.create(db,owner,command(delegate))
        await db.commit()
        node=(await approvals.list_items(db,delegate,'pending'))[0]
        assert not node['is_delegated']
        await approvals.decide(db,delegate,node['node_id'],DecideNodeCommand(operation_id='own',expected_revision=1,action='approve'))
        await db.commit()
        assert not await approvals.list_items(db,delegate,'pending')
        assert len(await approvals.list_items(db,owner,'pending'))==(1 if mode=='all' else 0)
        # An applicant with approval permissions can be a delegate generally, but never on their own application.
        from app.models.identity import OAUserRole
        role=await db.scalar(select(OAUserRole.role_id).where(OAUserRole.user_id==delegate.user_id))
        db.add(OAUserRole(tenant_id=owner.tenant_id,user_id=applicant.user_id,role_id=role))
        await db.commit()
        await service.revoke(db,owner,(await service.list_items(db,owner))[0]['id'],DelegationRevoke(operation_id='revoke',expected_revision=1))
        await db.commit()
        await service.create(db,owner,command(applicant))
        await db.commit()
        assert not await approvals.list_items(db,applicant,'pending')


async def test_scope_isolation_and_original_owner_keeps_authority(oa_db):
    async with oa_db() as db:
        owner,delegate,_,_,_=await submitted(db)
        await service.create(db,owner,command(delegate,scene='reimbursement'))
        await db.commit()
        assert not await approvals.list_items(db,delegate,'pending')
        pending=await approvals.list_items(db,owner,'pending')
        assert not pending[0]['is_delegated']
        await approvals.decide(db,owner,pending[0]['node_id'],DecideNodeCommand(operation_id='owner',expected_revision=1,action='approve'))
        await db.commit()
        assert not await approvals.list_items(db,delegate,'pending')


async def test_revoke_and_approval_serialize_without_duplicate_settlement(oa_db):
    import asyncio
    async with oa_db() as db:
        owner,delegate,_,applicant,_=await submitted(db)
        row=(await service.create(db,owner,command(delegate))).result
        await db.commit()
        node=(await approvals.list_items(db,delegate,'pending'))[0]['node_id']
    async def revoke():
        async with oa_db() as db:
            result=await service.revoke(db,owner,row['id'],DelegationRevoke(operation_id='race-revoke',expected_revision=1))
            await db.commit()
            return result
    async def decide():
        async with oa_db() as db:
            try:
                result=await approvals.decide(db,delegate,node,DecideNodeCommand(operation_id='race-decide',expected_revision=1,action='approve'))
                await db.commit()
                return result
            except AppException as exc:
                await db.rollback()
                return exc
    revoked,decision=await asyncio.gather(revoke(),decide())
    assert revoked.result['state']=='REVOKED'
    async with oa_db() as db:
        assert not await approvals.list_items(db,delegate,'pending')
        balance=await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==applicant.user_id))
        events=await db.scalar(select(func.count()).select_from(OAWorkflowEvent).where(OAWorkflowEvent.target_id==node,OAWorkflowEvent.action=='approval.decide'))
        if isinstance(decision,AppException):
            assert (balance.used,balance.reserved,events)==(0,1,0)
        else:
            assert (balance.used,balance.reserved,events)==(1,0,1)


async def test_delegation_http_validation_auth_and_revision_conflicts(oa_db):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from httpx import ASGITransport, AsyncClient
    from app.api.routers import oa_delegations
    from app.core.context import set_current_user
    from app.db.session import get_db
    async with oa_db() as db:
        owner,delegate,_,applicant,_=await submitted(db)
        outsider=await seed(db,resources=['approval'])
        await db.commit()
        app=FastAPI()
        app.include_router(oa_delegations.router,prefix='/api')
        async def database(): yield db
        app.dependency_overrides[get_db]=database
        @app.exception_handler(AppException)
        async def error(request,exc): return JSONResponse({'message':exc.message},status_code=exc.http_status)
        try:
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                set_current_user(None)
                assert (await client.get('/api/oa/delegations')).status_code==401
                set_current_user(applicant)
                assert (await client.get('/api/oa/delegations')).status_code==403
                set_current_user(owner)
                response=await client.get('/api/oa/delegations/candidates')
                assert response.status_code==200,response.text
                people=response.json()['data']
                assert delegate.user_id in [p['id'] for p in people]
                payload=command(delegate).model_dump(mode='json')
                for changes in ({'reason':' '},{'scene':'ticket'},{'ends_at':payload['starts_at']},{'starts_at':'2026-10-23T10:00:00'},{'extra':'unknown'}):
                    assert (await client.post('/api/oa/delegations',json=payload|changes)).status_code==422
                response=await client.post('/api/oa/delegations',json=payload)
                assert response.status_code==200,response.text
                row=response.json()['data']['result']
                assert (await client.post('/api/oa/delegations',json=payload)).json()['data']['replayed']
                assert (await client.post('/api/oa/delegations',json=payload|{'reason':'不同内容'})).status_code==409
                await db.rollback()
                set_current_user(outsider)
                assert (await client.get('/api/oa/delegations')).json()['data']==[]
                assert (await client.post('/api/oa/delegations/'+row['id']+'/revoke',json={'operation_id':'cross','expected_revision':1})).status_code==404
                await db.rollback()
                set_current_user(owner)
                assert (await client.post('/api/oa/delegations/'+row['id']+'/revoke',json={'operation_id':'stale','expected_revision':9})).status_code==409
                await db.rollback()
                assert (await client.post('/api/oa/delegations/'+row['id']+'/revoke',json={'operation_id':'valid','expected_revision':1})).status_code==200
        finally: set_current_user(None)


async def test_delegated_reimbursement_uses_original_workflow_and_preserves_attribution(oa_db,monkeypatch):
    from tests.api.test_oa_reimbursement import setup,draft,invoice,fields
    from app.services import oa_reimbursement_service as reimbursements
    from app.schemas.oa_reimbursement import ReimbursementDraftPatch
    from app.schemas.oa_leave import SubmitLeaveCommand
    async with oa_db() as db:
        owner,applicant,workflow=await setup(db)
        delegate=await seed(db,tenant=owner.tenant_id,department=owner.depts[0],resources=['approval'],scope='self')
        await db.commit()
        key=await draft(db,applicant,workflow)
        attachment=await invoice(db,applicant,key,monkeypatch)
        await reimbursements.update_draft(db,applicant,key,ReimbursementDraftPatch(operation_id='edit',expected_revision=2,fields=fields(attachment_ids=[attachment])))
        await db.commit()
        await reimbursements.submit(db,applicant,key,SubmitLeaveCommand(operation_id='submit',expected_revision=3,requested_submission_version=1))
        await db.commit()
        saved=(await service.create(db,owner,command(delegate,scene='reimbursement'))).result
        await db.commit()
        node=(await approvals.list_items(db,delegate,'pending'))[0]
        assert node['scene']=='reimbursement' and node['is_delegated']
        result=await approvals.decide(db,delegate,node['node_id'],DecideNodeCommand(operation_id='approve-reimbursement',expected_revision=1,action='approve'))
        await db.commit()
        assert result.result['state']=='APPROVED'
        seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node['node_id']))
        assert seat.effective_user_id==owner.user_id and seat.decided_by==delegate.user_id
        assert seat.decision_delegation_id==saved['id']


@pytest.mark.parametrize('flag',['substituted','escalated'])
async def test_admin_reassigned_or_escalated_seat_cannot_be_delegated_again(oa_db,flag):
    async with oa_db() as db:
        owner,delegate,_,_,_=await submitted(db)
        node=(await approvals.list_items(db,owner,'pending'))[0]['node_id']
        seat=await db.scalar(select(OAWorkflowSeat).where(OAWorkflowSeat.node_id==node))
        setattr(seat,flag,True)
        await db.commit()
        await service.create(db,owner,command(delegate))
        await db.commit()
        assert not await approvals.list_items(db,delegate,'pending')
        with pytest.raises(AppException): await approvals.node_context(db,delegate,node)
