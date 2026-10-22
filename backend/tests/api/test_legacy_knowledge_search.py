"""Legacy timestamp columns still enforce validity and permission filters."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.repositories import knowledge_repo


@pytest.mark.asyncio
@pytest.mark.parametrize("zone", [timezone.utc, timezone(timedelta(hours=8))])
async def test_legacy_search_handles_utc_timestamps_and_filters(graph_ready, zone):
    now = datetime.now(zone)
    vector = [1.0] + [0.0] * (get_settings().embedding_dim - 1)
    async with async_session_factory() as session:
        ids = {}
        for label, tags, start, end in [
            ("allowed", ["search-probe"], now - timedelta(days=1), now + timedelta(days=1)),
            ("private", ["other-dept"], None, None),
            ("expired", [], None, now - timedelta(days=1)),
            ("future", [], now + timedelta(days=1), None),
        ]:
            doc = await knowledge_repo.add_document(session, title=label, format="md",
                permission_tags=tags, owner_id="u_admin_001", content_hash=label,
                status="published", effective_at=start, expire_at=end)
            ids[label] = str(doc.id)
            if start is not None:
                assert doc.effective_at == start.astimezone(timezone.utc).replace(tzinfo=None)
            await knowledge_repo.add_chunk(session, document_id=doc.id, chunk_index=0,
                content=label, embedding=vector, content_hash=label,
                source_location="probe", token_count=1)
        results = await knowledge_repo.search_chunks(session, query_vector=vector,
            permission_tags=["search-probe"], top_k=100)
        selected = {item["document_id"] for item in results}
        assert ids["allowed"] in selected
        assert not (selected & {ids["private"], ids["expired"], ids["future"]})
        public = await knowledge_repo.search_chunks(session, query_vector=vector,
            permission_tags=[], top_k=100)
        assert not ({item["document_id"] for item in public} & set(ids.values()))
        await session.rollback()
