"""Migration checks use a disposable schema in the verified test database only."""
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.db.migrations import migration_config


@pytest.fixture
def migration_db(safe_database):
    schema = "migration_test_" + uuid4().hex
    engine = create_engine(safe_database.database_sync_url)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public"))
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        # Never inherit alembic_version from public (which belongs to another
        # test). Give each temporary schema its own empty migration ledger.
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        yield connection
        connection.execute(text("SET search_path TO public"))
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    engine.dispose()


def migrate(connection, revision):
    config = migration_config()
    config.attributes["connection"] = connection
    command.upgrade(config, revision)


def test_mvp_upgrade_retains_all_existing_rows(migration_db):
    db = migration_db
    migrate(db, "0001")
    thread_id, document_id = uuid4(), uuid4()
    db.execute(text("INSERT INTO agent_thread(id,user_id,tenant_id,scene,status) VALUES (:id,'u_emp_001','t_001','leave','WAITING_HUMAN')"), {"id": thread_id})
    db.execute(text("INSERT INTO audit_event(action,thread_id) VALUES ('human_decided',:id)"), {"id": thread_id})
    db.execute(text("INSERT INTO knowledge_document(id,title,version,status,format,permission_tags) VALUES (:id,'existing',1,'published','md','{}')"), {"id": document_id})
    # Simulate an unversioned create_all MVP without touching its data.
    db.execute(text("DELETE FROM alembic_version"))
    migrate(db, "head")
    migrate(db, "head")
    assert db.execute(text("SELECT status FROM agent_thread WHERE id=:id"), {"id": thread_id}).scalar_one() == "WAITING_HUMAN"
    assert db.execute(text("SELECT COUNT(*) FROM audit_event")).scalar_one() == 1
    assert db.execute(text("SELECT title FROM knowledge_document WHERE id=:id"), {"id": document_id}).scalar_one() == "existing"


def test_migrations_match_registered_models(migration_db):
    from app.db.base import Base
    from app import models  # noqa: F401
    migrate(migration_db, "head")
    def current_application_table(obj, name, kind, reflected, compare_to):
        if kind == "table" and reflected and name not in Base.metadata.tables:
            return False  # LangGraph owns checkpoint tables in public.
        return True

    differences = compare_metadata(MigrationContext.configure(migration_db, opts={"include_object": current_application_table}), Base.metadata)
    assert differences == []


def test_adopts_unversioned_create_all_mvp_schema(migration_db):
    from app.db.base import Base
    from app import models  # noqa: F401
    # Represents an actual pre-migration checkout, not the baseline migration.
    original_mvp_tables = {"agent_thread", "agent_message", "precheck_result", "human_decision",
                           "ticket_context", "knowledge_document", "knowledge_chunk", "audit_event", "agent_policy"}
    for table in Base.metadata.sorted_tables:
        if table.name in original_mvp_tables:
            table.create(migration_db)
    row_id = uuid4()
    migration_db.execute(text("INSERT INTO agent_thread(id,user_id,tenant_id,scene,status) VALUES (:id,'u_emp_001','t_001','leave','WAITING_HUMAN')"), {"id": row_id})
    migrate(migration_db, "head")
    assert migration_db.execute(text("SELECT COUNT(*) FROM agent_thread WHERE id=:id"), {"id": row_id}).scalar_one() == 1


def test_existing_incompatible_mvp_schema_is_not_stamped(migration_db):
    migration_db.execute(text("CREATE TABLE agent_thread (id integer PRIMARY KEY)"))
    with pytest.raises(RuntimeError, match="不兼容"):
        migrate(migration_db, "head")
