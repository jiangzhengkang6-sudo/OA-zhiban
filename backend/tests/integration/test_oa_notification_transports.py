"""Formal ticket -> outbox -> actual providers -> receipts, with no external sends."""
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
import json

import pytest
from sqlalchemy import select

from app.models.oa_notification import OANotificationDelivery, OANotificationAttempt
from app.models.oa_ticket import OATicket
from app.providers import smtp, wecom
from app.services import oa_notification_service as service, oa_notification_worker as worker
from tests.api.test_oa_notification import setup, enqueue
from tests.api.test_oa_wecom import route
from tests.oa_support import oa_db
from tests.unit.test_oa_smtp import capture_smtp


@pytest.mark.parametrize('smtp_disconnect,wecom_code,smtp_state,wecom_state', [
    (False, 0, 'ACCEPTED', 'ACCEPTED'),
    (True, 0, 'UNKNOWN', 'ACCEPTED'),
    (False, None, 'ACCEPTED', 'UNKNOWN'),
    (False, 45009, 'ACCEPTED', 'PENDING'),
])
async def test_business_notification_transport_receipts_and_duplicate_boundary(
        oa_db, monkeypatch, smtp_disconnect, wecom_code, smtp_state, wecom_state):
    requests = []

    class Connection:
        def __init__(self, host, timeout):
            assert host == 'qyapi.weixin.qq.com'

        def connect(self):
            pass

        def request(self, method, path, body, headers):
            assert method == 'POST'
            assert path.startswith('/cgi-bin/webhook/send?key=fake-key-')
            requests.append(json.loads(body))

        def getresponse(self):
            if wecom_code is None:
                raise TimeoutError('synthetic ambiguous acceptance')
            return type('Response', (), {'status': 200,
                'read': lambda self, size: json.dumps({'errcode': wecom_code}).encode()})()

        def close(self):
            pass

    monkeypatch.setattr(wecom.http.client, 'HTTPSConnection', Connection)
    with capture_smtp(disconnect=smtp_disconnect) as (port, messages):
        async with oa_db() as db:
            handler, owner = await setup(db)
            settings = route(monkeypatch, handler)
            settings.smtp_enabled = True
            settings.smtp_host, settings.smtp_port = '127.0.0.1', port
            settings.smtp_from = 'oa@example.test'
            settings.smtp_starttls = False
            settings.smtp_username = settings.smtp_password = ''
            settings.notification_app_url = 'https://oa.example.test/oa/notifications'
            monkeypatch.setattr(smtp, 'get_settings', lambda: settings)
            monkeypatch.setattr(wecom, 'get_settings', lambda: settings)
            await service.save_contact(db, handler, handler.user_id, email='member@example.test',
                enabled=True, wecom_enabled=True, operation_id='consent')
            await db.commit()
            ticket = await enqueue(db, owner)
            # Dispatch replay must not create extra channel rows.
            await service.dispatch(db, tenant_id=owner.tenant_id)
            await db.commit()

        for channel in ('smtp', 'wecom'):
            assert await worker.run_once(oa_db, tenant_id=owner.tenant_id, channel=channel) == 1
            assert await worker.run_once(oa_db, tenant_id=owner.tenant_id, channel=channel) == 0
        assert len(messages) == len(requests) == 1
        parsed = BytesParser(policy=policy.default).parsebytes(messages[0])
        assert parsed['To'] == 'member@example.test'
        assert parsed['Subject'] == 'OA 业务提醒'
        assert parsed.get_content().strip() == requests[0]['text']['content'].strip()
        assert settings.notification_app_url in parsed.get_content()
        for sensitive in ('电脑无法启动', owner.user_id, handler.user_id, 'member@example.test'):
            assert sensitive not in requests[0]['text']['content']
            assert sensitive not in parsed.get_content()

        async with oa_db() as db:
            rows = (await db.scalars(select(OANotificationDelivery).where(
                OANotificationDelivery.tenant_id == owner.tenant_id))).all()
            assert len(rows) == 3
            assert {row.channel: row.state for row in rows} == {
                'inbox': 'ACCEPTED', 'smtp': smtp_state, 'wecom': wecom_state}
            assert next(row.message_id for row in rows if row.channel == 'smtp') == parsed['Message-ID']
            attempts = (await db.scalars(select(OANotificationAttempt).where(
                OANotificationAttempt.tenant_id == owner.tenant_id))).all()
            assert len(attempts) == 2
            assert (await db.get(OATicket, ticket['id'])).state == 'OPEN'
            inbox = await service.list_inbox(db, handler)
            assert len(inbox) == 1 and inbox[0]['delivered'] is True
            if wecom_state == 'PENDING':
                row = next(row for row in rows if row.channel == 'wecom')
                row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                await db.commit()

        if wecom_state == 'PENDING':
            wecom_code = 0
            assert await worker.run_once(oa_db, tenant_id=owner.tenant_id, channel='wecom') == 1
            assert len(requests) == 2 and len(messages) == 1
            async with oa_db() as db:
                row = await db.scalar(select(OANotificationDelivery).where(
                    OANotificationDelivery.tenant_id == owner.tenant_id,
                    OANotificationDelivery.channel == 'wecom'))
                assert row.state == 'ACCEPTED' and row.attempt_count == 2
