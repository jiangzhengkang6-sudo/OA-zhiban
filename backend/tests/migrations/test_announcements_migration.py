from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import create_engine, text
from app.db.migrations import migration_config


def test_upgrade_preserves_existing_identity_and_refuses_destroying_announcements(safe_database):
    engine=create_engine(safe_database.database_sync_url)
    try:
        with engine.connect() as db:
            transaction=db.begin()
            original=db.dialect.default_schema_name
            try:
                schema='announcement_'+uuid4().hex
                db.execute(text('CREATE SCHEMA '+schema))
                db.execute(text('SET LOCAL search_path TO '+schema+', public'))
                db.dialect.default_schema_name=schema
                db.execute(text('CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)'))
                config=migration_config()
                config.attributes['connection']=db
                command.upgrade(config,'0030')
                db.execute(text("INSERT INTO oa_department(id,tenant_id,name,enabled) VALUES ('dept','migration','原有部门',true)"))
                db.execute(text("INSERT INTO oa_user(id,tenant_id,normalized_username,display_name,password_hash,status,auth_version,authorization_version,failed_attempts,handoff_pending) VALUES ('user','migration','user','原有成员','unused','active',1,1,0,false)"))
                command.upgrade(config,'head')
                command.upgrade(config,'head')
                assert db.scalar(text("SELECT display_name FROM oa_user WHERE id='user'"))=='原有成员'
                command.downgrade(config,'0030')
                command.upgrade(config,'head')
                db.execute(text("INSERT INTO oa_announcement(id,tenant_id,department_id,author_id,title,body,state,revision) VALUES ('notice','migration','dept','user','公告','正文','DRAFT',1)"))
                with pytest.raises(RuntimeError,match='禁止破坏性降级'):
                    command.downgrade(config,'0030')
                assert db.scalar(text('SELECT count(*) FROM oa_announcement'))==1
            finally:
                transaction.rollback()
                db.dialect.default_schema_name=original
    finally: engine.dispose()
