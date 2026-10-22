"""Real builtin login and middleware for isolated M3 HTTP acceptance tests."""
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx

from app.api.routers import auth
from app.core import config
from app.db.session import get_db
from app.db import session as db_session
from app.main import app
from app.middleware import auth as auth_middleware
from app.models.identity import OAUser
from app.services.credential_service import hash_password
from app.services import identity_service


@asynccontextmanager
async def authenticated_client(factory, monkeypatch, actor):
    settings = config.get_settings().model_copy(update={
        'auth_tenant_id': actor.tenant_id, 'auth_cookie_secure': False,
        'auth_allowed_origins': ['http://test'],
        'auth_jwt_secret': 'm3-http-test-only-secret-' * 4,
    })
    monkeypatch.setattr(config, 'get_settings', lambda: settings)
    monkeypatch.setattr(identity_service, 'get_settings', lambda: settings)
    monkeypatch.setattr(auth, 'get_settings', lambda: settings)
    monkeypatch.setattr(auth_middleware, 'get_settings', lambda: settings)
    monkeypatch.setattr(db_session, 'async_session_factory', factory)
    async def database():
        async with factory() as db:
            yield db
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = database
    password = 'M3-test-password-123!'
    async with factory() as db:
        user = await db.get(OAUser, actor.user_id)
        user.password_hash = hash_password(password)
        username = user.normalized_username
        await db.commit()
    try:
        # Login throttling is persistent and keyed by source, including successful logins.
        transport = httpx.ASGITransport(app=app, client=('m3-' + uuid4().hex, 123))
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
            csrf = await client.get('/api/auth/csrf')
            assert csrf.status_code == 200, csrf.text
            response = await client.post('/api/auth/login', json={'username': username, 'password': password},
                headers={'Origin': 'http://test', 'x-csrf-token': csrf.json()['data']['token']})
            assert response.status_code == 200, response.text
            token = response.json()['data']['access_token']
            assert not token.startswith('mock:')
            client.headers['Authorization'] = 'Bearer ' + token
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
