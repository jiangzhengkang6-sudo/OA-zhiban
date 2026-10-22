"""Fresh-process startup verifies AI isolation without using the graph fixture."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from tests.oa_support import oa_db


def test_disabled_full_manual_loop_preserves_checkpoints(oa_db):
    script = textwrap.dedent('''
        import asyncio
        import os
        from uuid import uuid4
        from unittest.mock import AsyncMock, patch
        import psycopg
        from sqlalchemy import select
        from langgraph.checkpoint.postgres import PostgresSaver
        from langgraph.checkpoint.base import empty_checkpoint
        from app import main
        from app.db.session import async_session_factory
        from app.llm.base import LLMFactory
        from app.adapters.mock_adapter import MockAdapter
        from app.models.oa_leave import OALeaveBalance, OALeaveLedger
        from app.models.oa_workflow import OAWorkflowOutbox
        from app.schemas.oa_leave import BalanceAdjustment, LeaveDraftCreate, SubmitLeaveCommand, OACommand
        from app.schemas.oa_workflow import DecideNodeCommand
        from app.services import oa_leave_service as leaves, oa_balance_service as balances, oa_approval_service as approvals
        from tests.api.test_oa_leave_lifecycle import setup_leave, fields

        url = os.environ['CHECKPOINTER_URL']
        with PostgresSaver.from_conn_string(url) as saver:
            saver.setup()
            saver.put({'configurable': {'thread_id': 'ai-off-' + uuid4().hex, 'checkpoint_ns': ''}},
                      empty_checkpoint(), {'source': 'input', 'step': -1, 'parents': {}}, {})

        def snapshots():
            with psycopg.connect(url) as conn:
                return {table: conn.execute('SELECT row_to_json(t)::text FROM ' + table + ' t ORDER BY 1').fetchall()
                        for table in ['checkpoints', 'checkpoint_blobs', 'checkpoint_writes', 'checkpoint_migrations']}

        before = snapshots()
        assert before['checkpoints']
        forbidden = AssertionError('人工 OA 调用了 AI、旧 OA 适配器或外部网络')

        async def run():
            main.runtime.initialize = AsyncMock(side_effect=forbidden)
            main.runtime.close = AsyncMock(side_effect=forbidden)
            with patch.object(LLMFactory, 'get_llm', side_effect=forbidden), \
                 patch.object(LLMFactory, 'get_embedding', side_effect=forbidden), \
                 patch('httpx.AsyncClient.request', side_effect=forbidden), \
                 patch('app.services.scheduler._tick', new=AsyncMock(side_effect=forbidden)):
                for name in dir(MockAdapter):
                    if not name.startswith('_') and callable(getattr(MockAdapter, name)):
                        setattr(MockAdapter, name, lambda *a, **kw: (_ for _ in ()).throw(forbidden))
                async with main.lifespan(main.app):
                    async with async_session_factory() as db:
                        admin, actor, workflow = await setup_leave(db)
                        await balances.adjust(db, admin, BalanceAdjustment(operation_id='quota', expected_revision=0,
                            user_id=actor.user_id, leave_type='annual', year=2026, total=10, reason='隔离验收'))
                        await db.commit()
                        for index, action in enumerate(['approve', 'reject', 'withdraw']):
                            draft = await leaves.create_draft(db, actor, LeaveDraftCreate(operation_id='create-'+action,
                                workflow_definition_id=workflow, fields=fields(f'2026-11-{index+1:02d}', f'2026-11-{index+1:02d}')))
                            await db.commit()
                            leave_id = draft.result['id']
                            submitted = await leaves.submit(db, actor, leave_id, SubmitLeaveCommand(operation_id='submit-'+action,
                                expected_revision=1, requested_submission_version=1))
                            await db.commit()
                            if action == 'withdraw':
                                result = await leaves.withdraw(db, actor, leave_id, OACommand(operation_id='withdraw',
                                    expected_revision=submitted.result['revision']))
                            else:
                                node = next(n for n in await approvals.list_items(db, admin, 'pending') if n['leave_id']==leave_id)
                                result = await approvals.decide(db, admin, node['node_id'], DecideNodeCommand(operation_id=action,
                                    expected_revision=node['revision'], action=action, note='人工决定'))
                            await db.commit()
                            current = await leaves.detail(db, actor, leave_id)
                            assert current['state'] == {'approve':'APPROVED', 'reject':'REJECTED', 'withdraw':'CANCELLED'}[action]
                            await leaves.archive(db, actor, leave_id, OACommand(operation_id='archive-'+action,
                                expected_revision=current['revision']))
                            await db.commit()
                        account = await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
                        assert (account.used, account.reserved)==(1, 0)
                        events = (await db.scalars(select(OAWorkflowOutbox).where(OAWorkflowOutbox.tenant_id==actor.tenant_id))).all()
                        assert events and all(event.status=='PENDING' for event in events)
                        ledger = (await db.scalars(select(OALeaveLedger).where(OALeaveLedger.tenant_id==actor.tenant_id))).all()
                        assert len(ledger)==7
            main.runtime.initialize.assert_not_awaited()
            main.runtime.close.assert_not_awaited()
            assert snapshots()==before
        asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop)
    ''')
    env = {**os.environ, 'AI_ENABLED':'false', 'AUTH_PROVIDER':'builtin',
           'AUTH_JWT_SECRET':'test-only-secret-' * 4}
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[2],
                            env=env, capture_output=True, text=True, timeout=50)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('provider', ['builtin', 'mock'])
def test_disabled_lifecycle_and_entry_points_in_fresh_process(safe_database, provider):
    script = textwrap.dedent('''
        import asyncio
        from unittest.mock import AsyncMock
        from app import main
        from app.api.routers.auth import configuration
        from app.services.authorization_service import authorize_tool
        from app.core.context import CurrentUser
        from app.core.errors import AppException
        from app.graph.graph_service import runtime

        async def run():
            main.runtime.initialize = AsyncMock(side_effect=AssertionError('graph initialized'))
            main.runtime.close = AsyncMock(side_effect=AssertionError('graph closed'))
            main.run_scheduler = AsyncMock()
            async with main.lifespan(main.app):
                data = (await configuration()).data
                assert data['capabilities'] == {'manual_oa': main._settings.auth_provider == 'builtin', 'ai': False}
                for action in [lambda: runtime.invoke('unused', {}),
                               lambda: authorize_tool(CurrentUser(user_id='unused', tenant_id='test'), 'leave', 'get_leave_balance')]:
                    try:
                        await action()
                    except AppException as error:
                        assert error.http_status == 503 and '关闭' in error.message
                    else:
                        raise AssertionError('AI entry was allowed')
            main.runtime.initialize.assert_not_awaited()
            main.runtime.close.assert_not_awaited()
        asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop)
    ''')
    env = {**os.environ, 'AI_ENABLED': 'false', 'AUTH_PROVIDER': provider,
           'AUTH_JWT_SECRET': 'test-only-secret-' * 4}
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr


def test_ai_defaults_to_enabled():
    from app.core.config import Settings
    assert Settings(_env_file=None, ai_enabled=True).ai_enabled is True
