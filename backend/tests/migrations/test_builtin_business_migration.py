"""M3 upgrade checks use transactional schemas inside the approved test database."""
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from app.db.migrations import migration_config


def test_typed_workflow_upgrade_preserves_m2_and_enforces_subject(safe_database):
    engine = create_engine(safe_database.database_sync_url)
    try:
        with engine.connect() as db:
            transaction = db.begin()
            original = db.dialect.default_schema_name
            try:
                schema = 'm3_' + uuid4().hex
                db.execute(text('CREATE SCHEMA ' + schema))
                db.execute(text('SET LOCAL search_path TO ' + schema + ', public'))
                db.dialect.default_schema_name = schema
                db.execute(text('CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)'))
                config = migration_config()
                config.attributes['connection'] = db
                command.upgrade(config, '0024')
                # A real M2 submission exists before the upgrade, including an event.
                statements = [
                    "INSERT INTO oa_user(id,tenant_id,normalized_username,display_name,password_hash,status,auth_version,authorization_version,failed_attempts,handoff_pending) VALUES ('user','tenant','user','sentinel','unused','active',1,1,0,false)",
                    "INSERT INTO oa_department(id,tenant_id,name,enabled) VALUES ('dept','tenant','sentinel',true)",
                    "INSERT INTO oa_workflow_definition(id,tenant_id,department_id,code,name,scene,draft,revision,published_version) VALUES ('def','tenant','dept','leave','sentinel','leave','{}',1,1)",
                    "INSERT INTO oa_workflow_version(id,tenant_id,definition_id,version,form_version,rule_version,package,workflow_hash,form_hash,rule_hash,published_by) VALUES ('wf','tenant','def',1,1,1,'{}','w','f','r','user')",
                    "INSERT INTO oa_leave(id,tenant_id,business_no,applicant_id,department_id,workflow_definition_id,fields,revision,submission_version,state) VALUES ('leave','tenant','L1','user','dept','def','{}',1,1,'IN_REVIEW')",
                    "INSERT INTO oa_leave_version(id,tenant_id,leave_id,version,workflow_version_id,fields,attachments,precheck,differences,leave_type,start_date,end_date,days) VALUES ('lv','tenant','leave',1,'wf','{}','[]','{}','{}','annual','2026-10-19','2026-10-19',1)",
                    "INSERT INTO oa_workflow_instance(id,tenant_id,leave_version_id,route_snapshot,route_revision,revision,state) VALUES ('inst','tenant','lv','[]',1,1,'IN_REVIEW')",
                    "INSERT INTO oa_workflow_operation(id,tenant_id,actor_id,kind,target_id,target_version,operation_id,payload_hash,result) VALUES ('op','tenant','user','leave.submit','leave','1','original-key','hash','{}')",
                    "INSERT INTO oa_workflow_event(id,tenant_id,operation_id,actor_id,event_key,action,target_id,detail) VALUES ('event','tenant','op','user','op','leave.submit','leave','{}')",
                    "INSERT INTO oa_leave_balance(id,tenant_id,user_id,leave_type,year,total,used,reserved,revision) VALUES ('balance','tenant','user','annual',2026,10,2,1,3)",
                ]
                for statement in statements:
                    db.execute(text(statement))
                db.execute(text("INSERT INTO oa_leave_ledger(id,tenant_id,balance_id,leave_version_id,operation_id,kind,total_delta,used_delta,reserved_delta,before,after,reason) VALUES ('ledger','tenant','balance','lv','op','RESERVE',0,0,1,CAST(:before AS json),CAST(:after AS json),'sentinel reservation')"),
                    {'before':'{"reserved":0}','after':'{"reserved":1}'})
                command.upgrade(config, '0025')
                command.upgrade(config, '0025')
                assert db.execute(text('SELECT scene,leave_version_id,reimbursement_version_id FROM oa_workflow_instance WHERE id=\'inst\'')).one() == ('leave', 'lv', None)
                assert db.scalar(text("SELECT display_name FROM oa_user WHERE id='user'")) == 'sentinel'
                assert db.scalar(text("SELECT operation_id FROM oa_workflow_operation WHERE id='op'")) == 'original-key'
                assert db.execute(text("SELECT total,used,reserved,revision FROM oa_leave_balance WHERE id='balance'")).one() == (10,2,1,3)
                assert db.execute(text("SELECT kind,reserved_delta,reason FROM oa_leave_ledger WHERE id='ledger'")).one() == ('RESERVE',1,'sentinel reservation')
                tables = inspect(db).get_table_names(schema=schema)
                assert all(name in tables for name in ('oa_reimbursement', 'oa_reimbursement_version', 'oa_reimbursement_attachment'))
                db.execute(text("INSERT INTO oa_reimbursement(id,tenant_id,business_no,applicant_id,department_id,workflow_definition_id,fields,revision,submission_version,state) VALUES ('re','tenant','R1','user','dept','def','{}',1,1,'IN_REVIEW')"))
                version_sql = "INSERT INTO oa_reimbursement_version(id,tenant_id,reimbursement_id,version,workflow_version_id,fields,attachments,precheck,differences,amount_cents,currency) VALUES (:id,'tenant','re',:version,'wf','{}','[]','{}','{}',:amount,:currency)"
                db.execute(text(version_sql), dict(id='rv', version=1, amount=100001, currency='CNY'))
                instance_sql = "INSERT INTO oa_workflow_instance(id,tenant_id,scene,leave_version_id,reimbursement_version_id,route_snapshot,route_revision,revision,state) VALUES (:id,:tenant,:scene,:leave,:re,'[]',1,1,'IN_REVIEW')"
                db.execute(text(instance_sql), dict(id='ri',tenant='tenant',scene='reimbursement',leave=None,re='rv'))
                for scene, leave, reimbursement, tenant in [
                    ('leave', None, None, 'tenant'), ('leave', 'lv', 'rv', 'tenant'),
                    ('reimbursement', 'lv', None, 'tenant'), ('leave', None, 'rv', 'tenant'),
                    ('unknown', None, 'rv', 'tenant'), ('reimbursement', None, 'rv', 'other'),
                    ('reimbursement', None, 'rv', 'tenant'),
                ]:
                    with pytest.raises(IntegrityError), db.begin_nested():
                        db.execute(text(instance_sql), dict(id=uuid4().hex,tenant=tenant,scene=scene,leave=leave,re=reimbursement))
                for amount, currency in [(0,'CNY'),(-1,'CNY'),(100000000000,'CNY'),(100,'USD')]:
                    with pytest.raises(IntegrityError), db.begin_nested():
                        db.execute(text(version_sql), dict(id=uuid4().hex,version=2,amount=amount,currency=currency))
                columns = {c['name'] for c in inspect(db).get_columns('oa_workflow_event', schema=schema)}
                assert {'trace_id','target_version','changes'} <= columns
                with pytest.raises(RuntimeError, match='禁止直接删除正式业务表'):
                    command.downgrade(config, '0024')
                assert db.scalar(text('SELECT version_num FROM alembic_version')) == '0025'
                for revision in ('0026', '0027', '0028'):
                    command.upgrade(config, revision)
                    command.upgrade(config, revision)
                assert db.scalar(text('SELECT version_num FROM alembic_version')) == '0028'
                assert db.execute(text("SELECT scene,leave_version_id,reimbursement_version_id,state FROM oa_workflow_instance WHERE id='inst'")).one() == ('leave', 'lv', None, 'IN_REVIEW')
                assert db.execute(text("SELECT total,used,reserved,revision FROM oa_leave_balance WHERE id='balance'")).one() == (10, 2, 1, 3)
                assert db.execute(text("SELECT kind,reserved_delta,reason FROM oa_leave_ledger WHERE id='ledger'")).one() == ('RESERVE', 1, 'sentinel reservation')
                assert db.scalar(text("SELECT operation_id FROM oa_workflow_operation WHERE id='op'")) == 'original-key'
                assert db.scalar(text("SELECT action FROM oa_workflow_event WHERE id='event'")) == 'leave.submit'
                assert db.execute(text("SELECT scene,leave_version_id,reimbursement_version_id FROM oa_workflow_instance WHERE id='ri'")).one() == ('reimbursement', None, 'rv')
            finally:
                transaction.rollback()
                db.dialect.default_schema_name = original
    finally:
        engine.dispose()


def test_formal_ticket_upgrade_preserves_legacy_and_tenant_constraints(safe_database):
    engine=create_engine(safe_database.database_sync_url)
    try:
        with engine.connect() as db:
            transaction=db.begin()
            original=db.dialect.default_schema_name
            try:
                schema='m3_'+uuid4().hex
                db.execute(text('CREATE SCHEMA '+schema))
                db.execute(text('SET LOCAL search_path TO '+schema+', public'))
                db.dialect.default_schema_name=schema
                db.execute(text('CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)'))
                config=migration_config()
                config.attributes['connection']=db
                command.upgrade(config,'0025')
                legacy=uuid4()
                db.execute(text("INSERT INTO ticket_record(id,tenant_id,ticket_id,user_id,category,priority,impact,summary,status,context,idempotency_key,payload_hash) VALUES (:id,'tenant','legacy','legacy-user','其他','medium','个人','sentinel','open','{}','legacy-key','hash')"),dict(id=legacy))
                command.upgrade(config,'0026')
                command.upgrade(config,'0026')
                assert db.scalar(text('SELECT summary FROM ticket_record WHERE id=:id'),dict(id=legacy))=='sentinel'
                assert db.scalar(text('SELECT COUNT(*) FROM oa_ticket'))==0
                tables=inspect(db).get_table_names(schema=schema)
                assert {'oa_ticket','oa_ticket_assignment_rule','oa_ticket_feedback','oa_bridge_confirmation','oa_bridge_result'}<=set(tables)
                for tenant,user in [('tenant','u'),('other','v')]:
                    db.execute(text("INSERT INTO oa_user(id,tenant_id,normalized_username,display_name,password_hash,status,auth_version,authorization_version,failed_attempts,handoff_pending) VALUES (:user,:tenant,:user,'member','unused','active',1,1,0,false)"),dict(user=user,tenant=tenant))
                    db.execute(text("INSERT INTO oa_department(id,tenant_id,name,enabled) VALUES (:dept,:tenant,'dept',true)"),dict(dept=tenant,tenant=tenant))
                ticket_sql="INSERT INTO oa_ticket(id,tenant_id,business_no,owner_id,department_id,revision,state,category,priority,impact,summary,merged_requests) VALUES (:id,'tenant',:id,:owner,'tenant',:revision,:state,'other','medium','self','test','[]')"
                db.execute(text(ticket_sql),dict(id='valid',owner='u',revision=1,state='OPEN'))
                for owner,revision,state in [('v',1,'OPEN'),('u',0,'OPEN'),('u',1,'UNKNOWN')]:
                    with pytest.raises(IntegrityError),db.begin_nested():
                        db.execute(text(ticket_sql),dict(id=uuid4().hex,owner=owner,revision=revision,state=state))
                with pytest.raises(IntegrityError),db.begin_nested():
                    db.execute(text("INSERT INTO oa_bridge_confirmation(id,tenant_id,actor_id,action,object_id,object_version,payload_hash,expires_at) VALUES ('bad','tenant','v','ticket.create','u','0','hash',now())"))
                with pytest.raises(RuntimeError,match='禁止直接删除正式工单'):
                    command.downgrade(config,'0025')
                assert db.scalar(text('SELECT version_num FROM alembic_version'))=='0026'
            finally:
                transaction.rollback()
                db.dialect.default_schema_name=original
    finally: engine.dispose()


def test_notification_upgrade_keeps_outbox_and_enforces_channel_attempt_keys(safe_database):
    engine=create_engine(safe_database.database_sync_url)
    try:
        with engine.connect() as db:
            transaction=db.begin()
            original=db.dialect.default_schema_name
            try:
                schema='m3_'+uuid4().hex
                db.execute(text('CREATE SCHEMA '+schema))
                db.execute(text('SET LOCAL search_path TO '+schema+', public'))
                db.dialect.default_schema_name=schema
                db.execute(text('CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)'))
                config=migration_config()
                config.attributes['connection']=db
                command.upgrade(config,'0026')
                for tenant,user in [('tenant','u'),('other','v')]:
                    db.execute(text("INSERT INTO oa_user(id,tenant_id,normalized_username,display_name,password_hash,status,auth_version,authorization_version,failed_attempts,handoff_pending) VALUES (:user,:tenant,:user,'sentinel','unused','active',1,1,0,false)"),dict(tenant=tenant,user=user))
                db.execute(text("INSERT INTO oa_department(id,tenant_id,name,enabled) VALUES ('dept','tenant','department',true)"))
                db.execute(text("INSERT INTO oa_workflow_operation(id,tenant_id,actor_id,kind,target_id,target_version,operation_id,payload_hash,result) VALUES ('op','tenant','u','ticket.create','ticket','0','sentinel','hash','{}')"))
                db.execute(text("INSERT INTO oa_workflow_event(id,tenant_id,operation_id,actor_id,event_key,action,target_id,detail) VALUES ('event','tenant','op','u','op','ticket.create','ticket','{}')"))
                db.execute(text("INSERT INTO oa_workflow_outbox(id,tenant_id,event_id,recipient_id,status,payload) VALUES ('outbox','tenant','event','u','PENDING','{}')"))
                command.upgrade(config,'0027')
                command.upgrade(config,'0027')
                assert db.scalar(text("SELECT status FROM oa_workflow_outbox WHERE id='outbox'"))=='PENDING'
                assert db.scalar(text('SELECT COUNT(*) FROM oa_notification'))==0
                sql="INSERT INTO oa_notification(id,tenant_id,source_outbox_id,recipient_id,department_id,source) VALUES (:id,'tenant','outbox',:recipient,'dept','{}')"
                with pytest.raises(IntegrityError),db.begin_nested():
                    db.execute(text(sql),dict(id='bad',recipient='v'))
                db.execute(text(sql),dict(id='notification',recipient='u'))
                with pytest.raises(IntegrityError),db.begin_nested():
                    db.execute(text(sql),dict(id='duplicate',recipient='u'))
                delivery="INSERT INTO oa_notification_delivery(id,tenant_id,notification_id,channel,state,message_id,attempt_count) VALUES (:id,'tenant','notification',:channel,:state,'stable',0)"
                for channel,state in [('smtp','INVALID'),('invalid','PENDING')]:
                    with pytest.raises(IntegrityError),db.begin_nested():
                        db.execute(text(delivery),dict(id=uuid4().hex,channel=channel,state=state))
                db.execute(text(delivery),dict(id='delivery',channel='smtp',state='PENDING'))
                attempt="INSERT INTO oa_notification_attempt(id,tenant_id,delivery_id,number,token,state) VALUES (:id,'tenant','delivery',:number,:token,'PROCESSING')"
                db.execute(text(attempt),dict(id='attempt',number=1,token='token'))
                for number,token in [(1,'new'),(2,'token'),(0,'new')]:
                    with pytest.raises(IntegrityError),db.begin_nested():
                        db.execute(text(attempt),dict(id=uuid4().hex,number=number,token=token))
                with pytest.raises(RuntimeError,match='禁止直接删除通知和渠道记录'):
                    command.downgrade(config,'0026')
                assert db.scalar(text('SELECT version_num FROM alembic_version'))=='0027'
            finally:
                transaction.rollback()
                db.dialect.default_schema_name=original
    finally: engine.dispose()


def test_formal_ai_scope_upgrade_creates_tenant_authority_and_is_forward_only(safe_database):
    engine = create_engine(safe_database.database_sync_url)
    try:
        with engine.connect() as db:
            transaction = db.begin()
            original = db.dialect.default_schema_name
            try:
                schema = 'm3_' + uuid4().hex
                db.execute(text('CREATE SCHEMA ' + schema))
                db.execute(text('SET LOCAL search_path TO ' + schema + ', public'))
                db.dialect.default_schema_name = schema
                db.execute(text('CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)'))
                config = migration_config()
                config.attributes['connection'] = db
                command.upgrade(config, '0027')
                command.upgrade(config, '0028')
                command.upgrade(config, '0028')
                tables = inspect(db).get_table_names(schema=schema)
                assert {'oa_knowledge_binding', 'oa_agent_policy',
                        'oa_agent_policy_version', 'oa_business_audit'} <= set(tables)
                with pytest.raises(RuntimeError, match='禁止直接删除'):
                    command.downgrade(config, '0027')
                assert db.scalar(text('SELECT version_num FROM alembic_version')) == '0028'
            finally:
                transaction.rollback()
                db.dialect.default_schema_name = original
    finally:
        engine.dispose()
