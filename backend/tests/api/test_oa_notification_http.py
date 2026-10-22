import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport,AsyncClient
from app.core.errors import AppException
from app.core.context import set_current_user
from app.core.config import get_settings
from app.db.session import get_db
from tests.oa_support import oa_db,seed
from tests.api.test_oa_notification import setup,enqueue


async def test_manual_notifications_ai_off_and_private_contacts(oa_db):
    from app.api.routers import oa_notifications
    async with oa_db() as db:
        handler,owner=await setup(db)
        outsider=await seed(db,resources=['notification','notification_admin'])
        await db.commit()
        await enqueue(db,owner)
        app=FastAPI()
        prefix=get_settings().api_prefix
        app.include_router(oa_notifications.router,prefix=prefix)
        async def database(): yield db
        app.dependency_overrides[get_db]=database
        @app.exception_handler(AppException)
        async def error(request,exc): return JSONResponse({'message':exc.message},status_code=exc.http_status)
        set_current_user(handler)
        try:
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                response=await client.get(prefix+'/oa/notifications')
                assert response.status_code==200
                notification_id=response.json()['data'][0]['id']
                assert (await client.post(prefix+'/oa/notifications/'+notification_id+'/read')).status_code==200
                contact=prefix+'/oa/notifications/contacts/'+handler.user_id
                response=await client.put(contact,json=dict(email='private@example.test',enabled=True,operation_id='http-contact'))
                assert response.status_code==200
                assert (await client.get(contact)).json()['data']['email']=='private@example.test'
                response=await client.put(contact,json=dict(email='',enabled=False,wecom_enabled=True,operation_id='http-wecom'))
                assert response.status_code==200
                saved=(await client.get(contact)).json()['data']
                assert saved['wecom_enabled'] is True and saved['enabled'] is False
                assert saved['wecom_available'] is False
                assert 'webhook' not in str(saved).lower()
                other_contact=prefix+'/oa/notifications/contacts/'+owner.user_id
                response=await client.put(other_contact,json=dict(email='',enabled=False,wecom_enabled=True,operation_id='admin-cannot-grant'))
                assert response.status_code==403
                assert (await client.get(other_contact)).json()['data']['wecom_enabled'] is False
                assert (await client.get(prefix+'/oa/notifications/deliveries')).status_code==200
                set_current_user(owner)
                assert (await client.get(contact)).status_code==403
                assert (await client.post(prefix+'/oa/notifications/'+notification_id+'/read')).status_code==403
                assert (await client.get(prefix+'/oa/notifications/deliveries')).status_code==403
                set_current_user(outsider)
                assert (await client.get(contact)).status_code==404
                assert (await client.get(prefix+'/oa/notifications/deliveries')).json()['data']==[]
        finally: set_current_user(None)
