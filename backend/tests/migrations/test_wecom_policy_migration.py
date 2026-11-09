"""The cutover migration must preserve contact, inbox and existing receipts."""
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from app.db.migrations import migration_config


def test_policy_upgrade_is_additive_and_ledger_downgrade_is_guarded(safe_database):
    engine=create_engine(safe_database.database_sync_url)
    try:
        with engine.connect() as db:
            transaction=db.begin()
            original=db.dialect.default_schema_name
            try:
                schema='policy_'+uuid4().hex
                db.execute(text('CREATE SCHEMA '+schema))
                db.execute(text('SET LOCAL search_path TO '+schema+', public'))
                db.dialect.default_schema_name=schema
                db.execute(text('CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)'))
                config=migration_config()
                config.attributes['connection']=db
                command.upgrade(config,'0036')
                db.execute(text("INSERT INTO oa_user(id,tenant_id,normalized_username,display_name,password_hash,status,auth_version,authorization_version,failed_attempts,handoff_pending) VALUES ('u','t','u','sentinel','unused','active',1,1,0,false)"))
                db.execute(text("INSERT INTO oa_user_contact(id,tenant_id,user_id,email,enabled,wecom_enabled) VALUES ('c','t','u','sentinel@example.test',true,true)"))
                command.upgrade(config,'0037')
                command.upgrade(config,'0037')
                assert db.execute(text("SELECT enabled,wecom_enabled FROM oa_user_contact WHERE id='c'")).one()==(True,True)
                columns={column['name'] for column in inspect(db).get_columns('oa_notification_delivery',schema=schema)}
                assert {'wecom_batch_id','wecom_event_key','wecom_business_key','wecom_category'}<=columns
                db.execute(text("INSERT INTO oa_wecom_batch(id,tenant_id,destination_hash,state,lease_until) VALUES ('b','t','digest','UNKNOWN',now())"))
                with pytest.raises(RuntimeError,match='投递历史必须保留'): command.downgrade(config,'0036')
                assert db.scalar(text('SELECT version_num FROM alembic_version'))=='0037'
            finally:
                transaction.rollback()
                db.dialect.default_schema_name=original
    finally:
        engine.dispose()
