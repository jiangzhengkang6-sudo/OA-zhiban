"""Exercise real middleware and routers without crossing the two OA authorities."""
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.errors import AppException
from app.db.session import get_db
from app.middleware.auth import AuthMiddleware
from app.models.identity import OAUser
from app.models.oa_leave import OALeave
from app.models.oa_workflow import OAWorkflowOperation
from tests.oa_support import oa_db


async def test_mock_identity_is_denied_formal_routes_but_keeps_legacy_drafts(oa_db, monkeypatch):
    from app.core import config
    from app.middleware import auth
    from app.providers import identity
    from app.adapters import factory, mock_adapter
    from app.api.routers import leaves, oa_leaves, oa_approvals, oa_workflows, oa_balances, oa_administration

    settings = Settings(_env_file=None, auth_provider='mock', oa_provider='mock',
                        llm_provider='mock', embedding_provider='mock', ai_enabled=True)
    for module in (config, auth, identity, factory, mock_adapter):
        monkeypatch.setattr(module, 'get_settings', lambda: settings)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    for module in (leaves, oa_leaves, oa_approvals, oa_workflows, oa_balances, oa_administration):
        app.include_router(module.router, prefix='/api')

    @app.exception_handler(AppException)
    async def error_handler(request: Request, error: AppException):
        return JSONResponse({'message': str(error)}, status_code=error.http_status)

    async def session():
        async with oa_db() as db:
            yield db
    app.dependency_overrides[get_db] = session

    async def formal_counts():
        async with oa_db() as db:
            return [await db.scalar(select(func.count()).select_from(model))
                    for model in (OALeave, OAWorkflowOperation)]

    before = await formal_counts()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for username in ('u_emp_001', 'u_admin_001'):
            for path in ('leaves', 'approvals', 'workflows', 'workflows?available=true',
                         'workflows/options', 'balances', 'administration/instances', 'administration/reconciliation'):
                response = await client.get('/api/oa/' + path, headers={'Authorization': 'Bearer mock:' + username})
                assert response.status_code == 403, (username, path, response.text)
        created = await client.post('/api/leaves', headers={'Authorization': 'Bearer mock:u_emp_001'}, json={
            'leave_type': 'annual', 'start_at': '2026-10-20T09:00:00+08:00',
            'end_at': '2026-10-20T18:00:00+08:00', 'reason': 'M2 compatibility ' + uuid4().hex})
        assert created.status_code == 200
        draft = created.json()['data']
        assert draft['status'] == 'DRAFT'
        listing = await client.get('/api/leaves', headers={'Authorization': 'Bearer mock:u_emp_001'})
        assert listing.status_code == 200
        assert draft['application_id'] in [row['application_id'] for row in listing.json()['data']['items']]
    assert await formal_counts() == before


async def test_existing_admin_and_business_role_never_gain_formal_permissions(oa_db):
    from app.schemas.organization import RoleInput, UserCreate
    from app.services import identity_service as identities, organization_service as organization
    from app.services.authorization_service import require_permission
    from app.services.oa_access_service import OA_RESOURCES
    import pytest

    tenant = 'm2-compat-' + uuid4().hex
    async with oa_db() as db:
        admin_user = await identities.bootstrap_admin(db, 'admin', 'Test-password-123!', tenant_id=tenant)
        admin = await identities.current_identity(db, admin_user)
        role = await organization.save_role(db, admin, RoleInput(code='document_reader', name='文档查看', permissions=[
            dict(resource='document', action='read', scope='self')]))
        created = await organization.create_user(db, admin, UserCreate(username='reader', display_name='查看成员',
            password='Test-password-123!', role_ids=[role['id']]))
        reader = await identities.current_identity(db, await db.get(OAUser, created['id']))
        require_permission(reader, 'document', 'read')
        for actor in (admin, reader):
            assert not set(OA_RESOURCES) & {p['resource'] for p in actor.data_scope['permissions']}
            for resource in OA_RESOURCES:
                for action in ('read', 'write'):
                    with pytest.raises(AppException) as denied:
                        require_permission(actor, resource, action)
                    assert denied.value.http_status == 403
