"""Widen department tags without changing existing versions or permissions."""
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from app.db.migrations import migration_config


def test_upgrade_preserves_tags_and_accepts_full_department_ids(safe_database):
    engine = create_engine(safe_database.database_sync_url)
    try:
        with engine.connect() as db:
            transaction = db.begin()
            original = db.dialect.default_schema_name
            try:
                schema = 'knowledge_' + uuid4().hex
                db.execute(text('CREATE SCHEMA ' + schema))
                db.execute(text('SET LOCAL search_path TO ' + schema + ', public'))
                db.dialect.default_schema_name = schema
                db.execute(text('CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)'))
                config = migration_config()
                config.attributes['connection'] = db
                command.upgrade(config, '0029')
                source, version = str(uuid4()), str(uuid4())
                db.execute(text("INSERT INTO knowledge_source(id,name) VALUES (:id,'sentinel')"), {'id': source})
                db.execute(text("INSERT INTO knowledge_version(id,source_id,version,permission_tags) VALUES (:id,:source,1,ARRAY['employee'])"),
                    {'id': version, 'source': source})
                command.upgrade(config, 'head')
                command.upgrade(config, 'head')
                assert db.scalar(text('SELECT permission_tags FROM knowledge_version WHERE id=:id'), {'id': version}) == ['employee']
                department = str(uuid4())
                db.execute(text('UPDATE knowledge_version SET permission_tags=ARRAY[:department] WHERE id=:id'),
                    {'id': version, 'department': department})
                assert db.scalar(text('SELECT permission_tags FROM knowledge_version WHERE id=:id'), {'id': version}) == [department]
                with pytest.raises(RuntimeError, match='完整保留'):
                    command.downgrade(config, '0029')
            finally:
                transaction.rollback()
                db.dialect.default_schema_name = original
    finally:
        engine.dispose()
