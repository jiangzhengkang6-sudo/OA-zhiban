"""Additive drafting migrations and destructive downgrade protection."""
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text

from app.db.migrations import migration_config
from test_mvp_upgrade import migrate, migration_db  # noqa: F401


@pytest.mark.parametrize("scene", ["document", "email"])
def test_owned_drafting_tables_and_unique_revisions(migration_db, scene):
    migrate(migration_db, "head")
    inspector = inspect(migration_db)
    record, version = f"{scene}_record", f"{scene}_draft_version"
    assert {record, version}.issubset(inspector.get_table_names())
    assert any(c["column_names"] == ["tenant_id", "owner_id", "idempotency_key"]
               for c in inspector.get_unique_constraints(record))
    assert any(c["column_names"] == [f"{scene}_id", "version"]
               for c in inspector.get_unique_constraints(version))
    assert any(f["referred_table"] == record for f in inspector.get_foreign_keys(version))
    assert {"input_snapshot", "source_snapshot", "confirmation"}.issubset(
        {c["name"] for c in inspector.get_columns(record)})


def test_drafting_migrations_repeat_and_allow_empty_downgrade(migration_db):
    schema = migration_db.execute(text("SELECT current_schema()")).scalar_one()
    # Exercise drafting's own reversible range without crossing later OA guards.
    migrate(migration_db, "0018")
    migrate(migration_db, "0018")
    assert migration_db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0018"
    config = migration_config()
    config.attributes["connection"] = migration_db
    command.downgrade(config, "0016")
    assert "document_record" not in inspect(migration_db).get_table_names(schema=schema)
    assert "email_record" not in inspect(migration_db).get_table_names(schema=schema)
    migrate(migration_db, "0018")
    assert "document_record" in inspect(migration_db).get_table_names(schema=schema)


@pytest.mark.parametrize("scene,revision,target", [("document", "0017", "0016"), ("email", "0018", "0017")])
def test_nonempty_business_data_refuses_downgrade(migration_db, scene, revision, target):
    migrate(migration_db, revision)
    thread_id = uuid4()
    migration_db.execute(text("INSERT INTO agent_thread(id,user_id,tenant_id,scene,status) "
                              "VALUES (:id,'u_emp_001','t_001',:scene,'DRAFT')"),
                         {"id": thread_id, "scene": scene})
    columns = "id,thread_id,tenant_id,owner_id,subject,status,idempotency_key,input_snapshot,source_snapshot"
    values = ":id,:thread,'t_001','u_emp_001','retained','CREATED','keep','{}','[]'"
    columns += f",{scene}_id"
    values += ",'KEEP-1'"
    if scene == "document":
        columns += ",template_id,template_version,template_sections,recipient,deadline,classification,distribution"
        values += ",'notice',1,'[]','team','','internal','team'"
    migration_db.execute(text(f"INSERT INTO {scene}_record ({columns}) VALUES ({values})"),
                         {"id": uuid4(), "thread": thread_id})
    config = migration_config()
    config.attributes["connection"] = migration_db
    with pytest.raises(RuntimeError):
        command.downgrade(config, target)
    assert migration_db.execute(text(f"SELECT COUNT(*) FROM {scene}_record")).scalar_one() == 1
    assert migration_db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == revision
