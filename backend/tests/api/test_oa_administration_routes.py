from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from httpx import AsyncClient,ASGITransport
from app.core.context import set_current_user
from app.core.errors import AppException
from app.db.session import get_db
from tests.oa_support import oa_db
from tests.api.test_oa_approval_modes import submitted


async def test_management_routes_enforce_permissions_and_return_summaries(oa_db):
    from app.api.routers.oa_administration import router
    async with oa_db() as db:
        manager,_,replacement,applicant,_=await submitted(db)
    app=FastAPI()
    app.include_router(router,prefix='/api')
    active=[manager]
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
        response=await client.get('/api/oa/administration/instances')
        assert response.status_code==200
        instance=response.json()['data'][0]
        assert instance['nodes'][0]['seats'][0]['effective_user_name']=='测试成员'
        assert 'fields' not in instance and 'attachments' not in instance
        seat=instance['nodes'][0]['seats'][0]['id']
        response=await client.get('/api/oa/administration/seats/'+seat+'/candidates')
        assert response.status_code==200 and replacement.user_id in [u['id'] for u in response.json()['data']]
        active[0]=applicant
        assert (await client.get('/api/oa/administration/instances')).status_code==403
        assert (await client.get('/api/oa/administration/reconciliation')).status_code==403
        assert (await client.post('/api/oa/administration/seats/'+seat+'/transfer',json=dict(
            operation_id='blocked',expected_revision=1,target_user_id=replacement.user_id,reason='交接'))).status_code==403
        active[0]=manager
        response=await client.post('/api/oa/administration/seats/'+seat+'/transfer',json=dict(
            operation_id='transfer',expected_revision=1,target_user_id=replacement.user_id,reason='交接'))
        assert response.status_code==200 and response.json()['data']['result']['revision']==2
        updated=(await client.get('/api/oa/administration/instances')).json()['data'][0]['nodes'][0]['seats'][0]
        assert updated['effective_user_id']==replacement.user_id and updated['effective_user_name']=='测试成员'
        response=await client.get('/api/oa/administration/reconciliation')
        assert response.status_code==200 and response.json()['data']['read_only'] and response.json()['data']['ok']
        response=await client.post('/api/oa/administration/instances/'+instance['instance_id']+'/resume',json=dict(
            operation_id='invalid-resume',expected_revision=2,reason='未暂停'))
        assert response.status_code==422
