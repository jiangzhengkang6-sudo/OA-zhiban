"""Incremental P3 migrations, metadata shape and retained business records."""
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import inspect, text
from app.db.migrations import migration_config
from test_mvp_upgrade import migrate, migration_db  # noqa: F401


def test_p3_upgrade_from_p2_and_empty_roundtrip(migration_db):
    schema = migration_db.execute(text('SELECT current_schema()')).scalar_one()
    migrate(migration_db, '0018')
    thread = uuid4()
    migration_db.execute(text("INSERT INTO agent_thread(id,user_id,tenant_id,scene,status) VALUES (:id,'existing','t_001','ticket','DRAFT')"), {'id':thread})
    migrate(migration_db, '0022')
    assert migration_db.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '0022'
    assert migration_db.execute(text('SELECT user_id FROM agent_thread WHERE id=:id'), {'id':thread}).scalar_one() == 'existing'
    tables = inspect(migration_db).get_table_names(schema=schema)
    assert {'work_task', 'work_task_batch', 'report_record', 'report_version', 'contract_record', 'contract_source', 'contract_review_version'} <= set(tables)
    assert 'notification_scan_at' in {column['name'] for column in inspect(migration_db).get_columns('work_task', schema=schema)}
    config = migration_config()
    config.attributes['connection'] = migration_db
    command.downgrade(config, '0018')
    assert 'contract_record' not in inspect(migration_db).get_table_names(schema=schema)
    migrate(migration_db, 'head')


@pytest.mark.parametrize('kind,revision,target', [('work_task_batch','0019','0018'), ('report_record','0020','0019'), ('contract_record','0021','0020')])
def test_p3_nonempty_downgrade_is_refused(migration_db, kind, revision, target):
    migrate(migration_db, revision)
    thread = uuid4()
    migration_db.execute(text("INSERT INTO agent_thread(id,user_id,tenant_id,scene,status) VALUES (:id,'owner','t_001','contract','DRAFT')"), {'id':thread})
    common = "id,thread_id,tenant_id,owner_id,idempotency_key,status,current_version"
    values = ":id,:thread,'t_001','owner','keep','CREATED',0"
    if kind == 'work_task_batch':
        columns = ',batch_id,source_type,source_id,source_version,source_snapshot'
        extra = ",'KEEP','ticket','source','1','{}'"
    elif kind == 'report_record':
        columns = ',report_id,subject,plan,scope_fingerprint'
        extra = ",'KEEP','retained','{}','test'"
    else:
        columns = ',contract_id,title,reviewer_id,node_state'
        extra = ",'KEEP','retained','reviewer','{}'"
    migration_db.execute(text(f'INSERT INTO {kind} ({common}{columns}) VALUES ({values}{extra})'), {'id':uuid4(), 'thread':thread})
    config = migration_config()
    config.attributes['connection'] = migration_db
    with pytest.raises(RuntimeError):
        command.downgrade(config, target)
    assert migration_db.execute(text(f'SELECT COUNT(*) FROM {kind}')).scalar_one() == 1

