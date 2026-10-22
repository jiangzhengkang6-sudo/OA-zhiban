"""P3 tenant filters include business tasks that have no AgentThread."""
from datetime import datetime, timezone
import pytest
from sqlalchemy import select, text
from app.db.session import async_session_factory, engine
from app.models.agent_thread import AgentThread
from app.models.audit_event import AuditEvent
from app.models.contract_record import ContractRecord
from app.models.report_record import ReportRecord
from app.models.work_task_batch import WorkTaskBatch
from app.models.work_task import WorkTask
from app.repositories.audit_repo import query_events


@pytest.mark.asyncio
async def test_p3_audits_are_tenant_scoped_including_threadless_tasks(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text('TRUNCATE agent_thread, audit_event RESTART IDENTITY CASCADE'))
    async with async_session_factory() as session:
        for tenant in ['t_001', 'foreign']:
            for kind in ['contract', 'report', 'work_task']:
                business = f'{tenant}-{kind}'
                thread = AgentThread(tenant_id=tenant, user_id='u_emp_001', scene=kind, status='DRAFT', business_id=business)
                session.add(thread)
                await session.flush()
                common = dict(thread_id=thread.id, tenant_id=tenant, owner_id='u_emp_001', idempotency_key=business)
                if kind == 'contract':
                    record = ContractRecord(contract_id=business, reviewer_id='u_mgr_001', title='private', node_state={}, **common)
                elif kind == 'report':
                    record = ReportRecord(report_id=business, subject='private', plan={}, scope_fingerprint='test', **common)
                else:
                    record = WorkTaskBatch(batch_id=business, source_type='ticket', source_id='source', source_version='1', source_snapshot={}, **common)
                session.add(record)
                await session.flush()
                session.add(AuditEvent(action=kind + '_create', business_id=business, thread_id=thread.id,
                    target_type='work_task_batch' if kind == 'work_task' else kind, target_id=business))
                if kind == 'work_task':
                    task_id = tenant + '-task'
                    session.add(WorkTask(task_id=task_id, batch_id=record.id, tenant_id=tenant, creator_id='u_emp_001',
                        assignee_id='u_mgr_001', source_type='ticket', source_id='source', source_version='1', candidate_id=task_id,
                        source_refs=[], title='private', priority='medium', due_at=datetime.now(timezone.utc)))
                    session.add(AuditEvent(action='work_task_start', business_id=task_id, target_type='work_task', target_id=task_id))
        session.add(AuditEvent(action='tool_called', business_id='unrelated'))
        session.add(AuditEvent(action='contract_review', business_id='orphan', target_type='contract'))
        session.add(AuditEvent(action='work_task_start', business_id='orphan', target_type='work_task', target_id='orphan'))
        await session.commit()
        events, total = await query_events(session, meeting_tenant_id='t_001', page_size=100)
        assert total == 5
        assert {event.business_id for event in events} == {'unrelated', 't_001-contract', 't_001-report', 't_001-work_task', 't_001-task'}

