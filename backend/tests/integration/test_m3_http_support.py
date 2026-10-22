"""HTTP acceptance clients must not share a persistent login throttle bucket."""
from datetime import datetime, timezone

from app.models.identity import OAAuthThrottle
from app.services.identity_service import digest
from tests.integration.test_m3_document_sources import formal_documents
from tests.m3_http_support import authenticated_client
from tests.oa_support import oa_db, seed


async def test_http_clients_isolate_login_sources(formal_documents, monkeypatch):
    key = digest('login:127.0.0.1')
    async with formal_documents() as db:
        actor = await seed(db, resources=['thread'])
        bucket = await db.get(OAAuthThrottle, key)
        previous = (bucket.attempts, bucket.window_start) if bucket else None
        if bucket is None:
            bucket = OAAuthThrottle(key=key)
            db.add(bucket)
        bucket.attempts = 61
        bucket.window_start = datetime.now(timezone.utc)
        await db.commit()
    try:
        for _ in range(2):
            async with authenticated_client(formal_documents, monkeypatch, actor) as client:
                response = await client.get('/api/auth/me')
                assert response.status_code == 200, response.text
                assert response.json()['data']['user_id'] == actor.user_id
        async with formal_documents() as db:
            assert (await db.get(OAAuthThrottle, key)).attempts == 61
    finally:
        async with formal_documents() as db:
            bucket = await db.get(OAAuthThrottle, key)
            if previous:
                bucket.attempts, bucket.window_start = previous
            else:
                await db.delete(bucket)
            await db.commit()
