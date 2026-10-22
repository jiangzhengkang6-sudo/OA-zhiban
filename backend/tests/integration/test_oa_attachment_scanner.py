"""Business attachment authorization with actual TCP adapter and controlled peer."""
import pytest

from app.core.config import Settings
from app.core.errors import AppException
from app.providers import file_scanner
from app.schemas.oa_leave import LeaveDraftCreate
from app.services import oa_leave_service as leaves, oa_attachment_service as attachments
from tests.api.test_oa_leave_attachments import image_upload
from tests.api.test_oa_leave_lifecycle import setup_leave, fields
from tests.oa_support import oa_db
from tests.scanner_support import scanner_server


@pytest.mark.parametrize('reply,state,allowed', [
    (b'stream: OK\0', 'CLEAN', True),
    (b'stream: Test-Signature FOUND\0', 'REJECTED', False),
    (b'stream: engine unavailable ERROR\0', 'FAILED', False),
    (b'stream: OK', 'FAILED', False),
], ids=['clean', 'infected', 'error', 'disconnect'])
async def test_uploaded_attachment_uses_tcp_scan_and_blocks_unclean_files(oa_db, monkeypatch, reply, state, allowed):
    async with scanner_server(reply) as (port, requests):
        settings = Settings(_env_file=None, clamd_host='127.0.0.1', clamd_port=port)
        monkeypatch.setattr(file_scanner, 'get_settings', lambda: settings)
        async with oa_db() as db:
            _, actor, workflow = await setup_leave(db)
            draft = await leaves.create_draft(db, actor, LeaveDraftCreate(
                operation_id='draft', workflow_definition_id=workflow, fields=fields()))
            await db.commit()
            item = await attachments.upload(db, actor, draft.result['id'], image_upload(),
                operation_id='upload', expected_revision=1)
            await db.commit()
            attachment = item.result['attachment']
            assert attachment['scan_status'] == state
            if allowed:
                assert await attachments.preflight(db, actor, draft.result['id'], [attachment['id']])
            else:
                with pytest.raises(AppException):
                    await attachments.preflight(db, actor, draft.result['id'], [attachment['id']])
    assert len(requests) == 1
    assert requests[0]['content'].startswith(b'\x89PNG\r\n\x1a\n')
