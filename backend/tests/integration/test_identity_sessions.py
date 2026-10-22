import asyncio
from uuid import uuid4
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import Settings
from app.core.errors import AppException
from app.models.identity import OAUser
from app.services import identity_service as identities


@pytest.fixture
async def identity_db(safe_database):
    from alembic import command
    from app.db.migrations import migration_config
    await asyncio.to_thread(command.upgrade, migration_config(), 'head')
    engine = create_async_engine(safe_database.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def configured():
    return Settings(_env_file=None, auth_provider='builtin', auth_jwt_secret='test-only-secret-' * 4)


async def new_admin(factory):
    tenant = 'test-' + uuid4().hex
    async with factory() as db:
        user = await identities.bootstrap_admin(db, 'admin', 'Test-password-123!', tenant_id=tenant)
        return tenant, user.id


async def test_bootstrap_login_rotate_replay_logout(identity_db):
    tenant, user_id = await new_admin(identity_db)
    async with identity_db() as db:
        with pytest.raises(AppException):
            await identities.bootstrap_admin(db, 'other', 'Test-password-123!', tenant_id=tenant)
    async with identity_db() as db:
        issued = await identities.login(db, 'admin', 'Test-password-123!', source=uuid4().hex, tenant_id=tenant, settings=configured())
        assert 'refresh' not in issued.grant.model_dump()
        assert (await identities.resolve_access(issued.grant.access_token, session=db, settings=configured())).user_id == user_id
        rotated = await identities.rotate_refresh(issued.refresh, session=db, settings=configured())
        with pytest.raises(AppException):
            await identities.rotate_refresh(issued.refresh, session=db, settings=configured())
        with pytest.raises(AppException):
            await identities.resolve_access(rotated.grant.access_token, session=db, settings=configured())
    async with identity_db() as db:
        issued = await identities.login(db, 'admin', 'Test-password-123!', source=uuid4().hex, tenant_id=tenant, settings=configured())
        await identities.logout(issued.refresh, session=db)
        with pytest.raises(AppException):
            await identities.resolve_access(issued.grant.access_token, session=db, settings=configured())


async def test_parallel_failures_lock_and_parallel_refresh_revokes_family(identity_db):
    tenant, user_id = await new_admin(identity_db)
    async def fail():
        async with identity_db() as db:
            with pytest.raises(AppException):
                await identities.login(db, 'admin', 'wrong', source=uuid4().hex, tenant_id=tenant, settings=configured())
    await asyncio.gather(*(fail() for _ in range(5)))
    async with identity_db() as db:
        user = await db.get(OAUser, user_id)
        assert user.failed_attempts == 5 and user.locked_until is not None
        with pytest.raises(AppException):
            await identities.login(db, 'admin', 'Test-password-123!', source=uuid4().hex, tenant_id=tenant, settings=configured())
    tenant, _ = await new_admin(identity_db)
    async with identity_db() as db:
        issued = await identities.login(db, 'admin', 'Test-password-123!', source=uuid4().hex, tenant_id=tenant, settings=configured())
    async def refresh():
        async with identity_db() as db:
            try:
                return await identities.rotate_refresh(issued.refresh, session=db, settings=configured())
            except AppException:
                return None
    results = await asyncio.gather(refresh(), refresh())
    successful = [r for r in results if r]
    assert len(successful) == 1
    async with identity_db() as db:
        with pytest.raises(AppException):
            await identities.resolve_access(successful[0].grant.access_token, session=db, settings=configured())


async def test_auth_http_csrf_origin_and_password_change(identity_db, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from app.api.routers import auth
    from app.db.session import get_db
    tenant, _ = await new_admin(identity_db)
    config = configured().model_copy(update={'auth_tenant_id': tenant, 'auth_cookie_secure': False,
        'auth_allowed_origins': ['http://localhost:5182']})
    monkeypatch.setattr(auth, 'get_settings', lambda: config)
    async def db_dep():
        async with identity_db() as db:
            yield db
    app = FastAPI()
    app.include_router(auth.router, prefix='/api')
    app.dependency_overrides[get_db] = db_dep
    @app.exception_handler(AppException)
    async def handler(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({'message': exc.message}, status_code=exc.http_status)
    transport = httpx.ASGITransport(app=app, client=('identity-' + uuid4().hex, 123))
    async with httpx.AsyncClient(transport=transport, base_url='http://localhost:5182') as client:
        payload = {'username': 'admin', 'password': 'Test-password-123!'}
        assert (await client.post('/api/auth/login', json=payload)).status_code == 403
        csrf = (await client.get('/api/auth/csrf')).json()['data']['token']
        headers = {'Origin': 'http://localhost:5182', 'X-CSRF-Token': csrf}
        assert (await client.post('/api/auth/login', json=payload, headers={**headers, 'Origin': 'https://evil.invalid'})).status_code == 403
        response = await client.post('/api/auth/login', json=payload, headers=headers)
        assert response.status_code == 200
        assert 'httponly' in response.headers['set-cookie'].lower()
        access = response.json()['data']['access_token']
        assert (await client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + access})).status_code == 200
        response = await client.post('/api/auth/change-password', json={'current_password': payload['password'], 'new_password': 'Changed-password-123!'}, headers={**headers, 'Authorization': 'Bearer ' + access})
        assert response.status_code == 200
        assert (await client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + access})).status_code == 401
