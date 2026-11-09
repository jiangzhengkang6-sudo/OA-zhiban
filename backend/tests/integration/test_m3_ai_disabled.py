"""Exercise M3 manual lifecycles in a fresh process with AI construction forbidden."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap

from tests.oa_support import oa_db


def test_m3_manual_business_without_graph_models_or_external_network(oa_db):
    script = textwrap.dedent('''
        import asyncio
        from unittest.mock import AsyncMock, patch
        from app import main
        from app.llm.base import LLMFactory
        from app.schemas.oa_leave import SubmitLeaveCommand, OACommand
        from app.schemas.oa_workflow import DecideNodeCommand
        from app.schemas.oa_ticket import TicketHandleCommand, TicketFeedbackCommand, FormalTicketCommand
        from app.services import oa_reimbursement_service as reimbursements, oa_reimbursement_attachment_service as files
        from app.services import oa_approval_service as approvals, oa_ticket_service as tickets, oa_notification_service as notifications
        from app.db.session import async_session_factory
        from tests.api.test_oa_reimbursement import setup, draft
        from tests.api.test_oa_leave_attachments import image_upload
        from tests.api.test_oa_notification import setup as setup_ticket
        from tests.api.test_oa_ticket import proposal

        forbidden = AssertionError('M3 manual business invoked AI or external HTTP')

        async def run():
            main.run_scheduler = AsyncMock()
            main.runtime.initialize = AsyncMock(side_effect=forbidden)
            main.runtime.close = AsyncMock(side_effect=forbidden)
            with patch.object(LLMFactory, 'get_llm', side_effect=forbidden), \
                 patch.object(LLMFactory, 'get_embedding', side_effect=forbidden), \
                 patch('httpx.AsyncClient.request', side_effect=forbidden), \
                 patch('app.providers.file_scanner.scan_bytes', new=AsyncMock(return_value='CLEAN')):
                async with main.lifespan(main.app):
                    async with async_session_factory() as db:
                        admin, actor, workflow = await setup(db)
                        for action in ('approve', 'reject', 'withdraw'):
                            key = await draft(db, actor, workflow, 'ai-off-draft-' + action)
                            await files.upload(db, actor, key, image_upload(), operation_id='invoice-' + action, expected_revision=1)
                            await db.commit()
                            submitted = await reimbursements.submit(db, actor, key, SubmitLeaveCommand(operation_id='submit-' + action, expected_revision=2, requested_submission_version=1))
                            await db.commit()
                            if action == 'withdraw':
                                await reimbursements.withdraw(db, actor, key, OACommand(operation_id='withdraw', expected_revision=submitted.result['revision']))
                            else:
                                node = next(n for n in await approvals.list_items(db, admin, 'pending') if n['reimbursement_id'] == key)
                                detail = await approvals.node_context(db, admin, node['node_id'])
                                assert detail['fields']['amount'] == '1000.00'
                                await approvals.decide(db, admin, node['node_id'], DecideNodeCommand(operation_id='decide-' + action, expected_revision=node['revision'], action=action, note='人工验收'))
                            await db.commit()
                            current = await reimbursements.detail(db, actor, key)
                            assert current['state'] == {'approve':'APPROVED', 'reject':'REJECTED', 'withdraw':'CANCELLED'}[action]
                            if action == 'approve':
                                await reimbursements.archive(db, actor, key, OACommand(operation_id='archive', expected_revision=current['revision']))
                                await db.commit()
                                assert (await reimbursements.detail(db, actor, key))['archived_at']

                        handler, owner = await setup_ticket(db)
                        proposed = proposal('manual-create')
                        prepared = await tickets.prepare(db, owner, proposed)
                        await db.commit()
                        command = FormalTicketCommand(**proposed.model_dump(), confirmation_id=prepared['confirmation_id'])
                        created = await tickets.create_or_merge(db, owner, command, confirmation_id=prepared['confirmation_id'])
                        await db.commit()
                        replay = await tickets.create_or_merge(db, owner, command, confirmation_id=prepared['confirmation_id'])
                        assert replay.replayed and replay.result == created.result
                        await db.commit()
                        await notifications.dispatch(db, tenant_id=owner.tenant_id)
                        await db.commit()
                        inbox = await notifications.list_inbox(db, handler)
                        assert any(n['object_id'] == created.result['id'] for n in inbox)
                        item = next(n for n in inbox if n['object_id'] == created.result['id'])
                        await notifications.mark_read(db, handler, item['id'])
                        await db.commit()
                        assert (await notifications.list_inbox(db, handler))[0]['read_at']
                        resolved = await tickets.handle(db, handler, created.result['id'], TicketHandleCommand(operation_id='resolve', expected_revision=created.result['revision'], action='resolve', note='人工办理完成'))
                        await db.commit()
                        assert resolved.result['state'] == 'RESOLVED'
                        feedback = await tickets.feedback(db, owner, created.result['id'], TicketFeedbackCommand(operation_id='feedback', expected_revision=resolved.result['revision'], resolved=True, comment='本人确认已解决'))
                        await db.commit()
                        assert feedback.result['state'] == 'CLOSED'
            main.runtime.initialize.assert_not_awaited()
            main.runtime.close.assert_not_awaited()
        asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop)
    ''')
    env = {**os.environ, 'AI_ENABLED': 'false', 'AUTH_PROVIDER': 'builtin', 'OA_PROVIDER': 'builtin',
           'AUTH_JWT_SECRET': 'test-only-secret-' * 4, 'SMTP_ENABLED': 'false'}
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[2],
                            env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
