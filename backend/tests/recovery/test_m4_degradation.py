"""Synthetic outage records reconcile through the normal authorized command path."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.core.errors import AppException
from app.models.oa_leave import OALeaveBalance, OALeaveLedger
from app.models.oa_workflow import OAWorkflowEvent, OAWorkflowOutbox, OAWorkflowOperation
from app.schemas.oa_workflow import DecideNodeCommand
from app.services import oa_approval_service as approvals, oa_leave_service as leaves
from tests.oa_support import oa_db
from tests.api.test_oa_approval_modes import submitted
from tests.integration import test_ai_disabled_manual_oa as manual


async def test_ai_off_manual_lifecycle_preserves_checkpoints(oa_db):
    manual.test_disabled_full_manual_loop_preserves_checkpoints(oa_db)


@pytest.mark.parametrize('provider', ['builtin', 'mock'])
def test_ai_off_entry_points(safe_database, provider):
    manual.test_disabled_lifecycle_and_entry_points_in_fresh_process(safe_database, provider)


async def test_outage_record_replay_and_difference_reconciliation(oa_db):
    async with oa_db() as db:
        admin, _, _, actor, leave_id = await submitted(db)
        node = next(n for n in await approvals.list_items(db, admin, 'pending') if n['leave_id'] == leave_id)
        # A human signs this record while the system is unavailable. No success is inferred.
        record = dict(tenant_id=actor.tenant_id, operator_id=admin.user_id, object_id=leave_id,
            node_id=node['node_id'], expected_revision=node['revision'], action='approve',
            operation_id='m4-offline-' + uuid4().hex, recorded_at=datetime.now(timezone.utc).isoformat(),
            reconciliation_status='PENDING')
        assert datetime.fromisoformat(record['recorded_at']).utcoffset() is not None
        command = DecideNodeCommand(**{key: record[key] for key in
            ('operation_id', 'expected_revision', 'action')})
        result = await approvals.decide(db, admin, record['node_id'], command)
        await db.commit()
        assert not result.replayed

        async def snapshot():
            counts = [await db.scalar(select(func.count()).select_from(model).where(model.tenant_id==actor.tenant_id))
                for model in (OALeaveLedger, OAWorkflowEvent, OAWorkflowOutbox, OAWorkflowOperation)]
            balance = await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
            return counts, (balance.used, balance.reserved)

        before = await snapshot()
        assert (await approvals.decide(db, admin, record['node_id'], command)).replayed
        await db.commit()
        assert await snapshot() == before
        for changed in (command.model_copy(update={'action':'reject'}),
                        command.model_copy(update={'operation_id':'different-record'})):
            with pytest.raises(AppException):
                await approvals.decide(db, admin, record['node_id'], changed)
            await db.rollback()
        assert await snapshot() == before
        assert (await leaves.detail(db, actor, leave_id))['state'] == 'APPROVED'
        assert before[1] == (1, 0)
