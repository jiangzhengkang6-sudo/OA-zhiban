import asyncio
from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routers import organization
from app.core.context import set_current_user
from app.core.errors import AppException
from app.db.session import get_db
from app.models.identity import OAUser
from app.models.oa_notification import OANotificationDelivery
from app.models.oa_workflow import OAWorkflowOutbox
from app.ops import operations_monitor as ops
from app.services import identity_service as identities, oa_notification_service as notifications
from tests.integration.test_identity_sessions import configured
from tests.oa_support import oa_db, seed


async def test_alerts_http_requires_current_admin_and_organization_read_even_with_ai_disabled(oa_db,tmp_path,monkeypatch):
    async with oa_db() as db:
        tenant = 'ops-' + uuid4().hex
        user = await identities.bootstrap_admin(db,'admin','Test-password-123!',tenant_id=tenant)
        admin = await identities.current_identity(db,user)
        reader = await seed(db,tenant=tenant,resources=['organization'])
        other = await identities.bootstrap_admin(db,'admin','Test-password-123!',tenant_id='other-'+uuid4().hex)
        other_admin = await identities.current_identity(db,other)
        await db.commit()
        settings = configured().model_copy(update=dict(ai_enabled=False,auth_tenant_id=tenant,ops_state_dir=str(tmp_path)))
        from app.core import config
        monkeypatch.setattr(config,'get_settings',lambda:settings)
        await ops.tick(settings,checks=[ops.result('database','FAIL','unavailable')])
        app = FastAPI()
        app.include_router(organization.router,prefix='/api')
        async def database(): yield db
        app.dependency_overrides[get_db] = database
        @app.exception_handler(AppException)
        async def error(request,exc): return JSONResponse({'message':exc.message},status_code=exc.http_status)
        try:
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                set_current_user(None)
                assert (await client.get('/api/organization/operational-alerts')).status_code == 401
                set_current_user(reader)
                assert (await client.get('/api/organization/operational-alerts')).status_code == 403
                set_current_user(admin)
                response = await client.get('/api/organization/operational-alerts')
                assert response.status_code == 200, response.text
                assert response.json()['data']['checks'][0]['name'] == '数据库'
                assert 'tenant_id' not in response.json()['data']
                set_current_user(other_admin)
                response = await client.get('/api/organization/operational-alerts')
                assert response.status_code == 200 and response.json()['data']['checks'] == []
                assert response.json()['data']['state'] == 'unconfigured'
                set_current_user(admin)
                # A separate request performs the lifecycle change; do not edit a
                # tracked identity inside the preceding read request's session.
                async with oa_db() as administrative:
                    disabled = await administrative.get(OAUser,admin.user_id)
                    disabled.status = 'disabled'
                    await administrative.commit()
                assert (await client.get('/api/organization/operational-alerts')).status_code == 401
        finally: set_current_user(None)


async def test_database_backlog_uses_real_columns_cutoff_terminal_states_and_tenant(oa_db,safe_database):
    from tests.api.test_oa_notification import setup
    from tests.api.test_oa_ticket import create
    now = ops.utcnow()
    async with oa_db() as db:
        handler,owner = await setup(db)
        _,outsider = await setup(db)
        for index in range(3): await create(db,owner,'monitor-'+str(index))
        await create(db,outsider,'monitor-outside')
        outboxes = list((await db.scalars(select(OAWorkflowOutbox).where(OAWorkflowOutbox.tenant_id==owner.tenant_id).order_by(OAWorkflowOutbox.created_at))).all())
        assert len(outboxes) == 3
        await notifications.dispatch(db,tenant_id=owner.tenant_id,outbox_id=outboxes[0].id)
        await db.commit()
        settings = safe_database.model_copy(update={'auth_tenant_id':owner.tenant_id})
        assert (await asyncio.to_thread(ops.database_checks,settings,now))[1]['count'] == 0
        outboxes[1].created_at = now-timedelta(seconds=121)
        outboxes[2].status = 'FAILED'
        delivery = await db.scalar(select(OANotificationDelivery).where(OANotificationDelivery.tenant_id==owner.tenant_id,OANotificationDelivery.channel=='smtp'))
        delivery.state = 'UNKNOWN'
        other = await db.scalar(select(OAWorkflowOutbox).where(OAWorkflowOutbox.tenant_id==outsider.tenant_id))
        other.status = 'FAILED'
        await db.commit()
        result = await asyncio.to_thread(ops.database_checks,settings,now)
        assert result[0]['status'] == 'PASS' and result[1]['count'] == 3 and result[1]['status'] == 'FAIL'
        for row in outboxes: row.status = 'SENT'
        delivery.state = 'ACCEPTED'
        await db.commit()
        result = await asyncio.to_thread(ops.database_checks,settings,now)
        assert result[1]['status'] == 'PASS' and result[1]['count'] == 0
