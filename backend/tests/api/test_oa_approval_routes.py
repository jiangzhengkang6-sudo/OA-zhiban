import pytest
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from httpx import AsyncClient,ASGITransport
from app.core.context import set_current_user
from app.core.errors import AppException
from app.db.session import get_db
from tests.oa_support import oa_db
from tests.api.test_oa_approval_modes import submitted


async def test_http_current_node_decision_and_applicant_archive(oa_db):
    from app.api.routers.oa_approvals import router
    from app.api.routers.oa_leaves import router as leaves_router
    async with oa_db() as db:
        first,_,copied,actor,leave_id=await submitted(db,cc=True)
    app=FastAPI()
    app.include_router(router,prefix='/api')
    app.include_router(leaves_router,prefix='/api')
    active=[first]
    @app.middleware('http')
    async def identity(request,call_next):
        set_current_user(active[0])
        try: return await call_next(request)
        finally: set_current_user(None)
    @app.exception_handler(AppException)
    async def error(request: Request,exc: AppException):
        return JSONResponse({'message':str(exc)},status_code=exc.http_status)
    async def session():
        async with oa_db() as db: yield db
    app.dependency_overrides[get_db]=session
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        pending=await client.get('/api/oa/approvals?kind=pending')
        assert pending.status_code==200
        node=pending.json()['data'][0]['node_id']
        context=await client.get('/api/oa/approvals/nodes/'+node)
        assert context.status_code==200 and 'versions' not in context.json()['data']
        active[0]=copied
        assert (await client.get('/api/oa/approvals/nodes/'+node)).status_code==403
        active[0]=first
        payload=dict(operation_id='http',expected_revision=1,action='approve',approval_note='材料齐全')
        assert (await client.post('/api/oa/approvals/nodes/'+node+'/decisions',json={**payload,'start_date':'2027-01-01'})).status_code==422
        assert (await client.post('/api/oa/approvals/nodes/'+node+'/decisions',json=payload)).status_code==200
        assert (await client.post('/api/oa/approvals/nodes/'+node+'/decisions',json=payload)).json()['data']['replayed']
        assert (await client.get('/api/oa/approvals/nodes/'+node)).status_code==403
        active[0]=actor
        result=await client.post('/api/oa/leaves/'+leave_id+'/archive',json=dict(operation_id='archive',expected_revision=3))
        assert result.status_code==200 and result.json()['data']['result']['state']=='APPROVED'

