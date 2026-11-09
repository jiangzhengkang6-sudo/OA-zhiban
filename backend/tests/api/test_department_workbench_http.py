from uuid import uuid4
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from app.api.routers import oa_announcements, oa_work_items
from app.core.context import set_current_user
from app.core.errors import AppException
from app.db.session import get_db
from tests.oa_support import oa_db, seed


async def test_announcement_http_lifecycle_and_unauthorized_requests(oa_db):
    async with oa_db() as db:
        author = await seed(db, resources=['announcement','approval'])
        outsider = await seed(db, resources=['announcement'])
        await db.commit()
        app = FastAPI()
        app.include_router(oa_announcements.router, prefix='/api')
        app.include_router(oa_work_items.router, prefix='/api')
        async def database(): yield db
        app.dependency_overrides[get_db]=database
        @app.exception_handler(AppException)
        async def error(request, exc): return JSONResponse({'message':exc.message}, status_code=exc.http_status)
        try:
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                set_current_user(None)
                assert (await client.get('/api/oa/announcements')).status_code==401
                assert (await client.get('/api/oa/work-items')).status_code==401
                set_current_user(author)
                response = await client.post('/api/oa/announcements', json=dict(operation_id=uuid4().hex,
                    department_id=author.depts[0], title='验收公告', body='普通正文'))
                assert response.status_code==200, response.text
                row=response.json()['data']['result']
                command=dict(operation_id=uuid4().hex,expected_revision=1)
                assert (await client.post('/api/oa/announcements/'+row['id']+'/publish',json=command)).status_code==200
                assert (await client.post('/api/oa/announcements/'+row['id']+'/read')).status_code==200
                assert (await client.get('/api/oa/work-items?page_size=101')).status_code==422
                assert (await client.get('/api/oa/work-items?source=unknown')).status_code==422
                set_current_user(outsider)
                assert (await client.get('/api/oa/announcements/'+row['id'])).status_code==404
                assert (await client.get('/api/oa/work-items')).status_code==403
        finally: set_current_user(None)
