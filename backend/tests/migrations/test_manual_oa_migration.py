"""M2 schema checks run only on the dedicated M2 test database."""
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from app.db.migrations import migration_config


def test_manual_workflow_migration_preserves_identity_and_constraints(safe_database):
    engine = create_engine(safe_database.database_sync_url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            original_schema = connection.dialect.default_schema_name
            try:
                schema = 'm2_' + uuid4().hex
                connection.execute(text('CREATE SCHEMA ' + schema))
                connection.execute(text('SET LOCAL search_path TO ' + schema + ', public'))
                connection.dialect.default_schema_name = schema
                connection.execute(text('CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)'))
                config = migration_config()
                config.attributes['connection'] = connection
                command.upgrade(config, '0023')
                tenant, user = uuid4().hex, uuid4().hex
                connection.execute(text("INSERT INTO oa_user(id,tenant_id,normalized_username,display_name,password_hash,status,auth_version,authorization_version,failed_attempts,handoff_pending) VALUES (:u,:t,:u,'sentinel','unused','active',1,1,0,false)"), {'u': user, 't': tenant})
                command.upgrade(config, '0024')
                command.upgrade(config, '0024')
                tables = inspect(connection).get_table_names(schema=schema)
                names = ['workflow_definition','workflow_version','leave','leave_version','workflow_instance',
                         'workflow_node','workflow_seat','workflow_operation','workflow_event','workflow_outbox',
                         'leave_balance','leave_ledger','leave_attachment']
                assert all('oa_' + name in tables for name in names)
                assert connection.scalar(text('SELECT display_name FROM oa_user WHERE id=:u'), {'u': user}) == 'sentinel'
                for tenant_id, total, used, reserved in [(tenant, 2, 2, 1), ('other', 5, 0, 0), (tenant, 5, -1, 0)]:
                    with pytest.raises(IntegrityError):
                        with connection.begin_nested():
                            connection.execute(text("INSERT INTO oa_leave_balance(id,tenant_id,user_id,leave_type,year,total,used,reserved,revision) VALUES (:id,:t,:u,'annual',2026,:total,:used,:reserved,1)"),
                                dict(id=uuid4().hex, t=tenant_id, u=user, total=total, used=used, reserved=reserved))
                assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0024'
                with pytest.raises(RuntimeError, match='禁止直接删除正式业务表'):
                    command.downgrade(config, '0023')
                assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0024'
                assert connection.scalar(text('SELECT display_name FROM oa_user WHERE id=:u'), {'u': user}) == 'sentinel'
                assert all('oa_' + name in inspect(connection).get_table_names(schema=schema) for name in names)
            finally:
                transaction.rollback()
                connection.dialect.default_schema_name = original_schema
    finally:
        engine.dispose()
