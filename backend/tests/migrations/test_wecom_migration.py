"""Upgrade existing SMTP consent in a transactional schema; preserve history."""
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from app.db.migrations import migration_config


def test_wecom_upgrade_preserves_email_and_defaults_to_no_consent(safe_database):
    engine=create_engine(safe_database.database_sync_url)
    try:
        with engine.connect() as db:
            transaction=db.begin()
            original=db.dialect.default_schema_name
            try:
                schema='wecom_'+uuid4().hex
                db.execute(text('CREATE SCHEMA '+schema))
                db.execute(text('SET LOCAL search_path TO '+schema+', public'))
                db.dialect.default_schema_name=schema
                db.execute(text('CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)'))
                config=migration_config()
                config.attributes['connection']=db
                command.upgrade(config,'0028')
                db.execute(text("INSERT INTO oa_user(id,tenant_id,normalized_username,display_name,password_hash,status,auth_version,authorization_version,failed_attempts,handoff_pending) VALUES ('u','t','u','sentinel','unused','active',1,1,0,false)"))
                db.execute(text("INSERT INTO oa_user_contact(id,tenant_id,user_id,email,enabled) VALUES ('c','t','u','sentinel@example.test',true)"))
                command.upgrade(config,'0029')
                command.upgrade(config,'0029')
                assert db.execute(text("SELECT email,enabled,wecom_enabled FROM oa_user_contact WHERE id='c'")).one()==('sentinel@example.test',True,False)
                checks=inspect(db).get_check_constraints('oa_notification_delivery',schema=schema)
                assert any('wecom' in row['sqltext'] for row in checks)
                assert 'destination_hash' in {c['name'] for c in inspect(db).get_columns('oa_notification_delivery',schema=schema)}
                with pytest.raises(RuntimeError,match='投递历史必须保留'):
                    command.downgrade(config,'0028')
                assert db.scalar(text('SELECT version_num FROM alembic_version'))=='0029'
            finally:
                transaction.rollback()
                db.dialect.default_schema_name=original
    finally:
        engine.dispose()
