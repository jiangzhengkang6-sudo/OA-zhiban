from alembic import command
from sqlalchemy import inspect, text
import pytest
from app.db.migrations import migration_config
from tests.migrations.test_mvp_upgrade import migration_db, migrate


def test_delegation_upgrade_retains_identity_and_protects_history(migration_db):
    db=migration_db
    migrate(db,'0031')
    db.execute(text("INSERT INTO oa_department(id,tenant_id,name,enabled) VALUES ('dept','migration','原部门',true)"))
    for uid in ('owner','delegate'):
        db.execute(text("INSERT INTO oa_user(id,tenant_id,normalized_username,display_name,password_hash,status,auth_version,authorization_version,failed_attempts,handoff_pending) VALUES (:id,'migration',:id,:id,'unused','active',1,1,0,false)"),{'id':uid})
    migrate(db,'head')
    migrate(db,'head')
    assert db.scalar(text("SELECT count(*) FROM oa_user WHERE tenant_id='migration'"))==2
    assert 'decision_delegation_id' in {c['name'] for c in inspect(db).get_columns('oa_workflow_seat')}
    config=migration_config()
    config.attributes['connection']=db
    command.downgrade(config,'0031')
    migrate(db,'head')
    db.execute(text("INSERT INTO oa_approval_delegation(id,tenant_id,delegator_id,delegate_id,department_id,scene,starts_at,ends_at,reason,revision) VALUES ('delegation','migration','owner','delegate','dept','leave',now(),now()+interval '1 day','出差',1)"))
    with pytest.raises(RuntimeError,match='禁止破坏性降级'):
        command.downgrade(config,'0031')
    assert db.scalar(text('SELECT count(*) FROM oa_approval_delegation'))==1
