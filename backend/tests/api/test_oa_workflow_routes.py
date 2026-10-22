import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.api.routers.oa_workflows import router
from app.core.context import set_current_user
from app.core.errors import AppException
from app.db.session import get_db
from tests.oa_support import oa_db, seed
from tests.unit.test_oa_workflow_definition import definition


async def test_http_workflow_permissions_and_stable_save(oa_db):
    async with oa_db() as db:
        admin = await seed(db,resources=['workflow'])
        employee = await seed(db,tenant=admin.tenant_id,department=admin.depts[0],resources=['leave'])
        outsider = await seed(db,resources=['workflow'])
        await db.commit()
    app = FastAPI()
    app.include_router(router,prefix='/api')
    from app.api.routers.oa_leaves import router as leave_router
    from app.api.routers.oa_balances import router as balance_router
    app.include_router(leave_router,prefix='/api')
    app.include_router(balance_router,prefix='/api')
    active = [admin]
    @app.middleware('http')
    async def identity(request,call_next):
        set_current_user(active[0])
        try: return await call_next(request)
        finally: set_current_user(None)
    @app.exception_handler(AppException)
    async def error_handler(request: Request, error: AppException):
        return JSONResponse({'message':str(error)},status_code=error.http_status)
    async def session():
        async with oa_db() as db: yield db
    app.dependency_overrides[get_db] = session
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        payload = dict(operation_id='save',department_id=admin.depts[0],code='http',name='请假',definition=definition())
        saved = await client.post('/api/oa/workflows',json=payload)
        assert saved.status_code == 200
        assert (await client.post('/api/oa/workflows',json=payload)).json() == saved.json()
        active[0] = employee
        assert (await client.get('/api/oa/workflows')).status_code == 403
        assert (await client.get('/api/oa/workflows?available=true')).status_code == 200
        assert (await client.post('/api/oa/workflows',json=payload)).status_code == 403
        leave = await client.post('/api/oa/leaves',json=dict(operation_id='draft',workflow_definition_id=saved.json()['data']['id'],
            fields=dict(leave_type='annual',start_date='2026-10-20',end_date='2026-10-20',reason='测试')))
        assert leave.status_code == 200
        assert (await client.get('/api/oa/leaves/'+leave.json()['data']['result']['id'])).status_code == 200
        assert (await client.get('/api/oa/balances')).status_code == 403
        active[0] = outsider
        assert (await client.post('/api/oa/workflows',json=payload)).status_code == 403

