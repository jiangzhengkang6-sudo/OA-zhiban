"""Use actual domain services: aggregate visibility without a second task lifecycle."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from app.core.errors import AppException
from app.models.agent_thread import AgentThread
from app.models.identity import OAUserRole
from app.models.work_task import WorkTask
from app.models.work_task_batch import WorkTaskBatch
from app.services import oa_work_item_service as service, oa_approval_service as approvals
from app.schemas.oa_workflow import DecideNodeCommand
from tests.oa_support import oa_db, seed
from tests.api.test_oa_approval_modes import submitted


async def tasks(db, actor, other):
    thread = AgentThread(tenant_id=actor.tenant_id, user_id=actor.user_id, scene='work_task')
    db.add(thread)
    await db.flush()
    batch = WorkTaskBatch(batch_id='WB-'+uuid4().hex, thread_id=thread.id, tenant_id=actor.tenant_id,
        owner_id=actor.user_id, source_type='ticket', source_id='private-source', source_version='1',
        source_snapshot={'content':'private snapshot must not enter the aggregation'}, idempotency_key=uuid4().hex)
    db.add(batch)
    await db.flush()
    rows = []
    for index, (status, assignee) in enumerate([('OPEN',actor.user_id),('IN_PROGRESS',actor.user_id),
            ('COMPLETED',actor.user_id),('CANCELLED',actor.user_id),('OPEN',other.user_id)]):
        row = WorkTask(task_id='WT-'+uuid4().hex, batch_id=batch.id, tenant_id=actor.tenant_id,
            creator_id=actor.user_id, assignee_id=assignee, source_type='ticket', source_id='private-source',
            source_version='1', candidate_id=str(index), source_refs=['private-ref'], title='待办 '+str(index),
            priority='normal', due_at=datetime(2026,11,index+1,tzinfo=timezone.utc), status=status)
        db.add(row)
        rows.append(row)
    await db.commit()
    return rows


async def test_pending_approvals_use_current_seats_and_remove_completed_items(oa_db):
    async with oa_db() as db:
        actor, other, _, owner, leave_id = await submitted(db)
        result = await service.pending(db, actor)
        assert result['total']==1
        row = result['items'][0]
        assert row['source']=='approval' and row['href'].endswith(row['id'].removeprefix('approval:'))
        assert (await service.pending(db, other))['items']==[]
        node = (await approvals.list_items(db, actor, 'pending'))[0]
        await approvals.decide(db, actor, node['node_id'], DecideNodeCommand(operation_id=uuid4().hex,
            expected_revision=node['revision'], action='approve'))
        await db.commit()
        assert (await service.pending(db, actor))['items']==[]


async def test_pending_business_tasks_filter_assignee_status_and_paginate(oa_db):
    async with oa_db() as db:
        actor = await seed(db, resources=['work_task'])
        other = await seed(db, tenant=actor.tenant_id, department=actor.depts[0], resources=['work_task'])
        rows = await tasks(db, actor, other)
        first = await service.pending(db, actor, source='work_task', page_size=1)
        second = await service.pending(db, actor, source='work_task', page=2, page_size=1)
        assert first['total']==second['total']==2
        assert [first['items'][0]['business_id'],second['items'][0]['business_id']]==[row.task_id for row in rows[:2]]
        assert 'private' not in str(first)
        assert (await service.pending(db, other))['total']==1
        outsider = await seed(db, resources=['work_task'])
        await db.commit()
        assert (await service.pending(db, outsider))['total']==0
        await db.execute(delete(OAUserRole).where(OAUserRole.tenant_id==actor.tenant_id, OAUserRole.user_id==actor.user_id))
        await db.commit()
        with pytest.raises(AppException): await service.pending(db, actor)


async def test_ai_off_keeps_manual_approvals_and_skips_business_task_service(oa_db, monkeypatch):
    async with oa_db() as db:
        actor, *_ = await submitted(db)
        monkeypatch.setattr(service, 'get_settings', lambda:SimpleNamespace(ai_enabled=False))
        async def forbidden(*args, **kwargs): raise AssertionError('AI task service called')
        monkeypatch.setattr(service.work_task_service, 'list_tasks', forbidden)
        assert (await service.pending(db, actor))['total']==1
        assert (await service.pending(db, actor, source='work_task'))['total']==0
