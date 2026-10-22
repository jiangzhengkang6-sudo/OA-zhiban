import pytest
from uuid import uuid4
from sqlalchemy import update
from app.core.context import CurrentUser
from app.core.errors import AppException
from app.models.identity import OAUser
from app.services import identity_service as identities
from app.services.authorization_service import require_fresh_identity, authorize_resource
from tests.integration.test_identity_sessions import identity_db, new_admin, configured


@pytest.fixture
def builtin(monkeypatch):
    from app.providers import identity
    from app.core import config
    monkeypatch.setattr(identity, 'get_settings', configured)
    monkeypatch.setattr(config, 'get_settings', configured)


async def test_commit_rechecks_version_and_logout(identity_db, builtin):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from app.db.session import AuthorizedSession
    from app.models.audit_event import AuditEvent
    tenant, user_id = await new_admin(identity_db)
    factory = async_sessionmaker(identity_db.kw['bind'], class_=AuthorizedSession, expire_on_commit=False)
    async with factory() as work:
        await require_fresh_identity(CurrentUser(user_id, tenant), session=work)
        async with identity_db() as management:
            await management.execute(update(OAUser).where(OAUser.id == user_id).values(authorization_version=2))
            await management.commit()
        work.add(AuditEvent(action='test.denied', actor_id=user_id, result='success'))
        with pytest.raises(AppException):
            await work.commit()
        await work.rollback()
    async with identity_db() as db:
        issued = await identities.login(db, 'admin', 'Test-password-123!', source=uuid4().hex, tenant_id=tenant, settings=configured())
    async with factory() as work:
        actor = await identities.resolve_access(issued.grant.access_token, session=work, settings=configured())
        await require_fresh_identity(actor, session=work)
        async with identity_db() as other:
            await identities.logout(issued.refresh, session=other)
        with pytest.raises(AppException):
            await work.commit()


def test_department_scope_requires_explicit_resource_permission():
    from app.services.authorization_service import resource_clause, require_permission
    from app.models.document_record import DocumentRecord
    actor = CurrentUser('owner', 'tenant', depts=['dept-a'], data_scope={
        'identity_provider': 'builtin', 'permissions': [{'resource':'document','action':'read','scope':'department'}]})
    assert 'oa_membership' in str(resource_clause(actor, 'document', DocumentRecord.owner_id))
    with pytest.raises(AppException):
        require_permission(actor, 'document', 'write')


async def test_builtin_authority_never_uses_mock_and_disable_live(identity_db, monkeypatch):
    from app.providers import identity
    monkeypatch.setattr(identity, 'get_settings', configured)
    from app.core import config
    monkeypatch.setattr(config, 'get_settings', configured)
    tenant, user_id = await new_admin(identity_db)
    async with identity_db() as db:
        actor = await require_fresh_identity(CurrentUser(user_id, tenant), session=db)
        assert actor.roles == ['admin']
        assert not authorize_resource(actor, tenant, 'someone-else', required_roles=['admin']).allowed
    async with identity_db() as db:
        await db.execute(update(OAUser).where(OAUser.id == user_id).values(status='disabled'))
        await db.commit()
    async with identity_db() as db:
        with pytest.raises(AppException):
            await require_fresh_identity(actor, session=db)


async def test_unknown_mock_token_rejected_in_builtin(identity_db, monkeypatch):
    import httpx
    from fastapi import FastAPI, Request
    from app.middleware.auth import AuthMiddleware
    from app.core.context import get_current_user
    from app.middleware import auth
    monkeypatch.setattr(auth, 'get_settings', configured)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    @app.get('/')
    async def endpoint():
        return {'user': getattr(get_current_user(), 'user_id', None)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/', headers={'Authorization': 'Bearer mock:u_admin_001'})).json()['user'] is None
        assert (await client.get('/')).json()['user'] is None
