from alembic import command
from sqlalchemy import inspect, text
import pytest
from app.db.migrations import migration_config
from tests.migrations.test_mvp_upgrade import migration_db, migrate


def test_transcription_upgrade_and_guarded_downgrade(migration_db):
    db=migration_db
    migrate(db,'0037')
    migrate(db,'head')
    assert {'meeting_transcription','meeting_utterance'} <= set(inspect(db).get_table_names())
    assert any(fk['constrained_columns']==['tenant_id','speaker_id'] for fk in inspect(db).get_foreign_keys('meeting_utterance'))
    cfg=migration_config()
    cfg.attributes['connection']=db
    command.downgrade(cfg,'0037')
    migrate(db,'head')
    db.execute(text("INSERT INTO oa_user(id,tenant_id,normalized_username,display_name,password_hash,status,auth_version,authorization_version,failed_attempts,handoff_pending) VALUES ('host','migration','host','host','unused','active',1,1,0,false)"))
    db.execute(text("INSERT INTO oa_meeting(id,tenant_id,organizer_id,host_id,recorder_id,title,agenda,starts_at,ends_at,location,online_url,state,revision,invitation_version,cancel_reason,video_enabled,video_room_created) VALUES ('meeting','migration','host','host','host','meeting','agenda',now(),now()+interval '1 hour','room','','DRAFT',1,0,'',false,false)"))
    db.execute(text("INSERT INTO meeting_transcription(id,tenant_id,meeting_id,initiator_id,sdk_app_id,room_id,robot_id,state,message,partial,expires_at,attempts) VALUES ('job','migration','meeting','host',12345,'room','robot','QUEUED','',true,now()+interval '1 day',0)"))
    with pytest.raises(RuntimeError,match='审计记录'): command.downgrade(cfg,'0037')
    assert db.scalar(text("SELECT state FROM meeting_transcription WHERE id='job'"))=='QUEUED'
