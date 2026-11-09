"""Run DDL in an isolated transaction; never reset an existing application DB."""
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from app.db.migrations import migration_config
from sqlalchemy.engine import make_url
from uuid import uuid4


def test_upgrade_retains_history_and_is_repeatable(safe_database):
    name = 'oa_migration_' + uuid4().hex + '_test'
    assert name.startswith('oa_migration_') and name.endswith('_test')
    control = create_engine(safe_database.database_sync_url, isolation_level='AUTOCOMMIT')
    with control.connect() as admin:
        admin.execute(text('CREATE DATABASE "' + name + '"'))
    engine = create_engine(make_url(safe_database.database_sync_url).set(database=name))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                config = migration_config()
                config.attributes['connection'] = connection
                command.upgrade(config, '0022')
                connection.execute(text("INSERT INTO agent_thread (id, user_id, tenant_id, scene, status) VALUES ('edfe8dfc-ff0c-4850-b193-7712defadf00', 'historical-user', 'historical-tenant', 'leave', 'RUNNING')"))
                command.upgrade(config, '0023')
                assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0023'
                command.upgrade(config, 'head')
                command.upgrade(config, 'head')
                assert 'oa_user' in inspect(connection).get_table_names()
                assert connection.scalar(text("SELECT user_id FROM agent_thread WHERE id='edfe8dfc-ff0c-4850-b193-7712defadf00'")) == 'historical-user'
                assert connection.scalar(text('SELECT version_num FROM alembic_version')) == ScriptDirectory.from_config(config).get_current_head()
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
        with control.connect() as admin:
            admin.execute(text('DROP DATABASE "' + name + '"'))
        control.dispose()
