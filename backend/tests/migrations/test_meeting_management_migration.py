from alembic import command
from sqlalchemy import inspect, text
import pytest
from app.db.migrations import migration_config
from tests.migrations.test_mvp_upgrade import migration_db, migrate


def test_meeting_upgrade_preserves_legacy_and_guards_downgrade(migration_db):
    db=migration_db
    migrate(db,'0033')
    db.execute(text("INSERT INTO agent_thread(id,user_id,tenant_id,scene,status) VALUES ('e2a644d7-071a-42b4-9faa-ef9b3e92e247','historical','migration','meeting','COMPLETED')"))
    migrate(db,'head')
    assert {'oa_meeting','oa_meeting_attendee'}.issubset(set(inspect(db).get_table_names()))
    assert db.scalar(text("SELECT user_id FROM agent_thread WHERE tenant_id='migration'"))=='historical'
    config=migration_config()
    config.attributes['connection']=db
    command.downgrade(config,'0033')
    migrate(db,'head')
    db.execute(text("INSERT INTO oa_user(id,tenant_id,normalized_username,display_name,password_hash,status,auth_version,authorization_version,failed_attempts,handoff_pending) VALUES ('host','migration','host','host','unused','active',1,1,0,false)"))
    db.execute(text("INSERT INTO oa_meeting(id,tenant_id,organizer_id,host_id,recorder_id,title,agenda,starts_at,ends_at,location,online_url,state,revision,invitation_version,cancel_reason) VALUES ('meeting','migration','host','host','host','meeting','agenda',now(),now()+interval '1 hour','room','','DRAFT',1,0,'')"))
    with pytest.raises(RuntimeError,match='禁止破坏性降级'): command.downgrade(config,'0033')
    assert db.scalar(text("SELECT title FROM oa_meeting WHERE id='meeting'"))=='meeting'


def test_video_meeting_upgrade_adds_opt_in_columns(migration_db):
    db=migration_db
    migrate(db,'0034')
    # 0034 creates ORM metadata in a fresh schema; existing installations receive 0035.
    migrate(db,'0035')
    assert {'video_enabled','video_room_created'}.issubset({c['name'] for c in inspect(db).get_columns('oa_meeting')})
    assert db.scalar(text("SELECT version_num FROM alembic_version"))=='0035'
