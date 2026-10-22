"""Real bytes, owner scope, fail-closed scanning and immutable references."""
import io
from uuid import UUID

import pytest
from PIL import Image
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.leave_attachment import LeaveAttachment
from app.models.approval_instance import ApprovalInstance
from app.models.audit_event import AuditEvent
from tests.api.test_builtin_leave_flow import client, emp_headers


def proof():
    buffer = io.BytesIO()
    Image.new('RGB', (2, 2), 'white').save(buffer, format='PNG')
    return buffer.getvalue()


async def draft(client, headers):
    response = await client.post('/api/leaves', json={
        'leave_type': 'sick', 'start_at': '2026-10-20T09:00:00+08:00',
        'end_at': '2026-10-20T18:00:00+08:00', 'reason': '就医',
    }, headers=headers)
    return response.json()['data']['application_id']


@pytest.mark.asyncio
async def test_upload_persists_bytes_metadata_and_pending_cannot_pass(client, emp_headers):
    aid = await draft(client, emp_headers)
    response = await client.post(f'/api/leaves/{aid}/attachments', headers=emp_headers,
                                 files={'file': ('proof.png', proof(), 'image/png')})
    assert response.status_code == 200
    attachment = response.json()['data']
    assert attachment['scan_status'] == 'PENDING'
    assert attachment['size_bytes'] == len(proof())
    assert len(attachment['sha256']) == 64
    assert 'storage_ref' not in attachment
    submitted = await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)
    assert submitted.json()['data']['status'] == 'NEEDS_FIX'
    assert any(i['item'] == 'attachment' and i['result'] == 'fail'
               for i in submitted.json()['data']['precheck']['items'])
    downloaded = await client.get(f'/api/leaves/{aid}/attachments/{attachment["attachment_id"]}/content', headers=emp_headers)
    assert downloaded.status_code == 409
    async with async_session_factory() as db:
        assert (await db.scalars(select(ApprovalInstance))).all() == []


@pytest.mark.asyncio
async def test_clean_scan_references_and_download_scope(client, emp_headers, monkeypatch):
    from app.providers import file_scanner
    async def clean(content):
        return 'CLEAN'
    monkeypatch.setattr(file_scanner, 'scan_bytes', clean)
    from app.adapters.factory import get_adapter
    from app.adapters.oa_adapter import Balance
    monkeypatch.setattr(get_adapter(), 'get_leave_balance',
                        lambda *args: Balance(leave_type='sick', total=5, used=4, remaining=1))
    aid = await draft(client, emp_headers)
    uploaded = await client.post(f'/api/leaves/{aid}/attachments', headers=emp_headers,
                                files={'file': ('proof.png', proof(), 'image/png')})
    assert uploaded.status_code == 200
    ref = uploaded.json()['data']['attachment_id']
    submitted = await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)
    assert submitted.json()['data']['status'] == 'SUBMITTED'
    downloaded = await client.get(f'/api/leaves/{aid}/attachments/{ref}/content', headers=emp_headers)
    assert downloaded.status_code == 200
    assert downloaded.content == proof()
    assert downloaded.headers['x-content-type-options'] == 'nosniff'
    denied = await client.get(f'/api/leaves/{aid}/attachments/{ref}/content',
                              headers={'Authorization': 'Bearer mock:u_cs_001'})
    assert denied.status_code == 403
    manager = await client.get(f'/api/leaves/{aid}/attachments',
                              headers={'Authorization': 'Bearer mock:u_mgr_001'})
    assert manager.status_code == 200
    assert manager.json()['data'][0]['filename'] == 'proof.png'
    async with async_session_factory() as db:
        row = await db.get(LeaveAttachment, UUID(ref))
        assert row.application_id == UUID(aid)
        assert (await db.scalars(select(AuditEvent).where(AuditEvent.action == 'leave_attachment_download'))).all()


@pytest.mark.asyncio
async def test_fake_cross_application_and_bad_file_uploads_are_rejected(client, emp_headers):
    aid = await draft(client, emp_headers)
    fake = await client.patch(f'/api/leaves/{aid}', headers=emp_headers, json={'attachments': ['proof.pdf']})
    assert fake.status_code == 400
    upload = await client.post(f'/api/leaves/{aid}/attachments', headers=emp_headers,
                              files={'file': ('proof.png', proof(), 'image/png')})
    ref = upload.json()['data']['attachment_id']
    other = await draft(client, emp_headers)
    crossed = await client.patch(f'/api/leaves/{other}', headers=emp_headers, json={'attachments': [ref]})
    assert crossed.status_code == 400
    for name, content, mime in [('proof.png', b'not an image', 'image/png'),
                                ('proof.exe', proof(), 'image/png'),
                                ('proof.png', proof(), 'application/pdf')]:
        bad = await client.post(f'/api/leaves/{aid}/attachments', headers=emp_headers,
                                files={'file': (name, content, mime)})
        assert bad.status_code == 400
    from app.core.config import get_settings
    limit = get_settings().attachment_max_bytes
    oversized = await client.post(f'/api/leaves/{aid}/attachments', headers=emp_headers,
                                  files={'file': ('proof.png', b'x' * (limit + 1), 'image/png')})
    assert oversized.status_code == 413


@pytest.mark.asyncio
@pytest.mark.parametrize('scan_status', ['ERROR', 'INFECTED'])
async def test_unusable_scan_status_blocks_precheck(client, emp_headers, monkeypatch, scan_status):
    from app.providers import file_scanner
    async def scan(content):
        return scan_status
    monkeypatch.setattr(file_scanner, 'scan_bytes', scan)
    aid = await draft(client, emp_headers)
    upload = await client.post(f'/api/leaves/{aid}/attachments', headers=emp_headers,
                              files={'file': ('proof.png', proof(), 'image/png')})
    assert upload.json()['data']['scan_status'] == scan_status
    submitted = await client.post(f'/api/leaves/{aid}/submit', headers=emp_headers)
    assert submitted.json()['data']['precheck']['passed'] is False
