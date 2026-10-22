from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text

from test_mvp_upgrade import migrate


@pytest.fixture
def migration_db(safe_database):
    schema = "meeting_migration_test_" + uuid4().hex
    engine = create_engine(safe_database.database_sync_url)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        yield connection
        connection.execute(text("SET search_path TO public"))
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


def test_meeting_migration_creates_domain_tables_and_constraints(migration_db):
    migrate(migration_db, "head")
    inspector = inspect(migration_db)

    expected = {
        "meeting_record",
        "meeting_source",
        "meeting_segment",
        "meeting_draft_version",
        "meeting_decision",
    }
    assert expected.issubset(set(inspector.get_table_names()))

    assert any(
        constraint["name"] == "uq_meeting_record_tenant_idempotency"
        for constraint in inspector.get_unique_constraints("meeting_record")
    )
    assert any(
        constraint["name"] == "uq_meeting_draft_version_number"
        for constraint in inspector.get_unique_constraints("meeting_draft_version")
    )
    assert any(
        constraint["name"] == "uq_meeting_decision_idempotency"
        for constraint in inspector.get_unique_constraints("meeting_decision")
    )

    source_columns = {column["name"] for column in inspector.get_columns("meeting_source")}
    segment_columns = {column["name"] for column in inspector.get_columns("meeting_segment")}
    assert {"content_hash", "storage_ref", "content_length"}.issubset(source_columns)
    assert {"ordinal", "start_offset", "end_offset", "text_hash", "locator"}.issubset(segment_columns)


def test_meeting_migration_is_idempotent(migration_db):
    migrate(migration_db, "0016")
    migrate(migration_db, "0016")
    assert migration_db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0016"
