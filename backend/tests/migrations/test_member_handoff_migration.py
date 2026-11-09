from alembic import command
from sqlalchemy import inspect, text
import pytest
from app.db.migrations import migration_config
from tests.migrations.test_mvp_upgrade import migration_db, migrate


def test_handoff_upgrade_and_protected_downgrade(migration_db):
    db=migration_db
    migrate(db,'0032')
    db.execute(text("INSERT INTO agent_thread(id,user_id,tenant_id,scene,status) VALUES ('edfe8dfc-ff0c-4850-b193-7712defadf00','historical','migration','work_task','RUNNING')"))
    migrate(db,'head')
    migrate(db,'head')
    assert 'handoff_department_id' in {c['name'] for c in inspect(db).get_columns('work_task')}
    assert db.scalar(text("SELECT user_id FROM agent_thread WHERE tenant_id='migration'"))=='historical'
    config=migration_config()
    config.attributes['connection']=db
    command.downgrade(config,'0032')
    migrate(db,'head')
    db.execute(text("INSERT INTO work_task_batch(id,batch_id,thread_id,tenant_id,owner_id,source_type,source_id,source_version,source_snapshot,idempotency_key,status,current_version) VALUES ('c82f4557-8858-4e40-8b80-cc021ec1fc31','batch','edfe8dfc-ff0c-4850-b193-7712defadf00','migration','historical','ticket','source','1','{}','key','CONFIRMED',1)"))
    db.execute(text("INSERT INTO work_task(id,task_id,batch_id,tenant_id,creator_id,assignee_id,source_type,source_id,source_version,candidate_id,source_refs,title,priority,sensitive,due_at,status,progress,version,deadline_version,handoff_department_id) VALUES ('7f6d9db2-eb24-4f83-a6fc-c8740bdbd17b','task','c82f4557-8858-4e40-8b80-cc021ec1fc31','migration','historical','receiver','ticket','source','1','candidate','[]','历史任务','normal',false,now(),'OPEN',0,2,2,'department')"))
    with pytest.raises(RuntimeError,match='禁止破坏性降级'):
        command.downgrade(config,'0032')
    assert db.scalar(text("SELECT creator_id FROM work_task WHERE task_id='task'"))=='historical'
