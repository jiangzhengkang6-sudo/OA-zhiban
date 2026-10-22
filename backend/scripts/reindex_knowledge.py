"""Rebuild all knowledge vectors before atomically changing their dimension.

Run from backend: python scripts/reindex_knowledge.py --apply
Without --apply, only inspect the database; no model requests or writes occur.
"""
import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.llm.base import LLMFactory

_ROWS = text("SELECT id::text AS id, content, embedding::text AS embedding "
             "FROM knowledge_chunk ORDER BY id")
_TYPE = text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
             "WHERE attrelid = 'knowledge_chunk'::regclass AND attname = 'embedding'")


def fingerprint(rows) -> str:
    return hashlib.sha256(json.dumps([dict(row) for row in rows],
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def rebuild(engine, embedder, dimension: int, *, apply: bool, backup_dir: Path) -> dict:
    if not 1 <= dimension <= 16000:
        raise RuntimeError("embedding dimension is outside pgvector limits")
    async with engine.connect() as connection:
        old_type = (await connection.execute(_TYPE)).scalar_one()
        rows = (await connection.execute(_ROWS)).mappings().all()
    result = {"chunks": len(rows), "old_type": old_type, "new_type": f"vector({dimension})"}
    if not apply:
        return {**result, "applied": False}

    vectors = []
    for start in range(0, len(rows), 8):
        batch = rows[start:start + 8]
        generated = await embedder.embed([row["content"] for row in batch])
        if len(generated) != len(batch) or any(len(vector) != dimension for vector in generated):
            raise RuntimeError("embedding batch failed validation; database is unchanged")
        vectors.extend(generated)

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / ("knowledge-vectors-" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ") + ".json")
    backup.write_text(json.dumps({"old_type": old_type,
        "rows": [{"id": row["id"], "embedding": row["embedding"]} for row in rows]},
        ensure_ascii=False), encoding="utf-8")

    async with engine.begin() as connection:
        await connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        await connection.execute(text("SET LOCAL statement_timeout = '30s'"))
        await connection.execute(text("LOCK TABLE knowledge_chunk IN ACCESS EXCLUSIVE MODE"))
        current = (await connection.execute(_ROWS)).mappings().all()
        if fingerprint(current) != fingerprint(rows):
            raise RuntimeError("knowledge changed during embedding; database is unchanged, rerun")
        if old_type != (await connection.execute(_TYPE)).scalar_one():
            raise RuntimeError("embedding column changed during rebuild; rerun")
        if old_type != f"vector({dimension})":
            # PostgreSQL DDL and every vector update roll back together on failure.
            await connection.execute(text(f"ALTER TABLE knowledge_chunk ALTER COLUMN embedding "
                f"TYPE vector({dimension}) USING NULL::vector({dimension})"))
        for row, vector in zip(rows, vectors):
            await connection.execute(text("UPDATE knowledge_chunk SET embedding = "
                "CAST(:embedding AS vector) WHERE id = CAST(:id AS uuid)"),
                {"id": row["id"], "embedding": json.dumps(vector)})
        count = (await connection.execute(text("SELECT count(*) FROM knowledge_chunk "
            "WHERE embedding IS NULL OR vector_dims(embedding) != :dimension"),
            {"dimension": dimension})).scalar_one()
        if count:
            raise RuntimeError("rebuild verification failed; transaction rolled back")
    return {**result, "applied": True, "backup": str(backup)}


async def main(apply: bool) -> None:
    settings = get_settings()
    if settings.embedding_provider == "mock" and apply:
        raise RuntimeError("select a real embedding provider before applying")
    engine = create_async_engine(settings.database_url)
    try:
        result = await rebuild(engine, LLMFactory.get_embedding(), settings.embedding_dim,
            apply=apply, backup_dir=Path(__file__).resolve().parents[2] / "data" / "backups")
        print(json.dumps(result), flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    options = parser.parse_args()
    try:
        asyncio.run(main(options.apply))
    except Exception as exc:
        # Transport/database exceptions may contain credentials or source text.
        print(json.dumps({"applied": False, "error_type": type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
