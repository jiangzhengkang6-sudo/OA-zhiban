"""Vector rebuild retains source rows and rolls back on failed or stale inputs."""
import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.reindex_knowledge import rebuild


@pytest.fixture
async def vector_database(safe_database):
    schema = "embedding_test_" + uuid4().hex
    setup = create_async_engine(safe_database.database_url)
    async with setup.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(safe_database.database_url,
        connect_args={"server_settings": {"search_path": schema + ",public"}})
    row_id = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE knowledge_chunk "
                "(id uuid PRIMARY KEY, content text NOT NULL, embedding vector(2))"))
            await connection.execute(text("INSERT INTO knowledge_chunk VALUES "
                "(:id, 'retained source text', '[1,0]')"), {"id": row_id})
        yield engine
    finally:
        await engine.dispose()
        async with setup.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await setup.dispose()


class Embedder:
    async def embed(self, texts):
        assert texts == ["retained source text"]
        return [[1.0, 0.0, 0.5]]


@pytest.mark.asyncio
async def test_rebuild_changes_dimensions_preserves_content_and_backs_up(vector_database, tmp_path):
    result = await rebuild(vector_database, Embedder(), 3, apply=True, backup_dir=tmp_path)
    assert result["applied"] and result["chunks"] == 1
    with open(result["backup"], encoding="utf-8") as file:
        backup = json.load(file)
    assert backup["old_type"] == "vector(2)"
    assert backup["rows"][0]["embedding"] == "[1,0]"
    async with vector_database.connect() as connection:
        row = (await connection.execute(text("SELECT id::text, content, vector_dims(embedding) "
            "FROM knowledge_chunk"))).one()
        assert row[0] == backup["rows"][0]["id"]
        assert row[1:] == ("retained source text", 3)


@pytest.mark.asyncio
async def test_inspection_does_not_call_provider_or_write(vector_database, tmp_path):
    result = await rebuild(vector_database, None, 3, apply=False, backup_dir=tmp_path)
    assert result == {"chunks": 1, "old_type": "vector(2)", "new_type": "vector(3)", "applied": False}
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_provider_failure_keeps_previous_vectors(vector_database, tmp_path):
    class Failed:
        async def embed(self, texts):
            raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await rebuild(vector_database, Failed(), 3, apply=True, backup_dir=tmp_path)
    async with vector_database.connect() as connection:
        assert (await connection.execute(text("SELECT embedding::text FROM knowledge_chunk"))).scalar_one() == "[1,0]"


@pytest.mark.asyncio
async def test_concurrent_edit_aborts_without_overwriting(vector_database, tmp_path):
    class Concurrent:
        async def embed(self, texts):
            async with vector_database.begin() as connection:
                await connection.execute(text("UPDATE knowledge_chunk SET content='new source text'"))
            return [[1, 0, 0.5]]

    with pytest.raises(RuntimeError, match="knowledge changed"):
        await rebuild(vector_database, Concurrent(), 3, apply=True, backup_dir=tmp_path)
    async with vector_database.connect() as connection:
        row = (await connection.execute(text("SELECT content, embedding::text FROM knowledge_chunk"))).one()
        assert row == ("new source text", "[1,0]")
