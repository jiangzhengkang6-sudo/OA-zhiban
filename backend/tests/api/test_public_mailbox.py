"""Real identity, real database; transports are stubbed, never send test-suite mail."""
import asyncio
from unittest.mock import Mock, AsyncMock
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from app.core.config import Settings
from app.core.errors import AppException
from app.models.public_mail import PublicMailboxMember, PublicMailMessage
from app.models.identity import OAUser
from app.schemas.public_mail import MailDraft, MailAction, MailMembers
from app.services import public_mail_service as mail
from tests.oa_support import oa_db, seed


async def setup(db, monkeypatch):
    owner = await seed(db, resources=['organization', 'email', 'work_task'])
    settings = Settings(_env_file=None, auth_provider='builtin', auth_tenant_id=owner.tenant_id,
        public_mailbox_enabled=True, smtp_enabled=True, smtp_host='smtp.example.com',
        smtp_from='office@example.com', smtp_username='office@example.com', smtp_password='test-only',
        imap_host='imap.example.com')
    monkeypatch.setattr(mail, 'get_settings', lambda: settings)
    await db.commit()
    result = await mail.setup(db, owner)
    await db.commit()
    return owner, result


def incoming(uid='1:1'):
    return dict(remote_key=uid, subject='验收材料', sender='client@example.com', recipients=['office@example.com'],
        body='请周五前提交验收报告。', attachments=[{'name': '清单.pdf', 'sensitive': False}],
        message_id='<source@example.com>', sent_at=None)


def stub_sync(monkeypatch, entries=None):
    receiver = Mock(return_value=dict(validity='1', last_uid=1, messages=entries or [incoming()], has_more=False))
    monkeypatch.setattr(mail.transport, 'receive', receiver)
    return receiver


async def received(db, owner, monkeypatch):
    stub_sync(monkeypatch)
    await mail.sync(db, owner)
    await db.commit()
    return (await mail.listing(db, owner))['items'][0]


def draft(**overrides):
    return MailDraft(**{'subject': '项目通知', 'recipients': ['receiver@example.com'], 'body': '会议在周五举行。',
        'idempotency_key': 'draft-1', **overrides})


async def test_explicit_membership_tenant_and_readonly(oa_db, monkeypatch):
    async with oa_db() as db:
        owner, box = await setup(db, monkeypatch)
        reader = await seed(db, tenant=owner.tenant_id, resources=['email'])
        outsider = await seed(db, resources=['organization', 'email'])
        admin = await seed(db, tenant=owner.tenant_id, resources=['organization', 'email'])
        await db.commit()
        assert (await mail.status(db, admin))['authorized'] is False
        for actor in [reader, outsider, admin]:
            with pytest.raises(AppException):
                await mail.listing(db, actor)
        db.add(PublicMailboxMember(mailbox_id=box['id'], user_id=reader.user_id))
        await db.commit()
        assert (await mail.listing(db, reader))['total'] == 0
        for call in [lambda: mail.save_draft(db, reader, draft()), lambda: mail.sync(db, reader), lambda: mail.member_options(db, reader)]:
            with pytest.raises(AppException):
                await call()
        (await db.get(OAUser, reader.user_id)).status = 'disabled'
        await db.flush()
        db.info.pop('identity_actors', None)
        await db.commit()
        with pytest.raises(AppException):
            await mail.listing(db, reader)


async def test_sync_is_deduplicated_and_does_not_call_ai(oa_db, monkeypatch):
    async with oa_db() as db:
        owner, _ = await setup(db, monkeypatch)
        receiver = stub_sync(monkeypatch)
        analyzer = Mock(side_effect=AssertionError('automatic AI'))
        monkeypatch.setattr(mail.email_service, 'analyze', analyzer)
        assert (await mail.sync(db, owner))['added'] == 1
        await db.commit()
        assert (await mail.sync(db, owner))['added'] == 0
        await db.commit()
        result = await mail.listing(db, owner)
        assert result['total'] == 1
        assert 'body' not in result['items'][0]
        detail = await mail.detail(db, owner, result['items'][0]['id'])
        assert detail['attachments'][0]['name'] == '清单.pdf'
        assert detail['body'] == '请周五前提交验收报告。'
        assert receiver.call_args.args[1:] == ('1', 1)
        analyzer.assert_not_called()


@pytest.mark.parametrize('outcome', ['ACCEPTED', 'UNKNOWN', 'FAILED'])
async def test_send_requires_confirmation_and_never_retries(oa_db, monkeypatch, outcome):
    async with oa_db() as db:
        owner, _ = await setup(db, monkeypatch)
        saved = await mail.save_draft(db, owner, draft())
        await db.commit()
        assert saved['version'] == 1 and saved['status'] == 'DRAFT'
        sender = Mock(return_value=outcome)
        monkeypatch.setattr(mail.transport, 'send_message', sender)
        with pytest.raises(AppException):
            await mail.action(db, owner, saved['id'], MailAction(action='send', expected_version=1))
        sender.assert_not_called()
        await db.rollback()
        sent = await mail.action(db, owner, saved['id'], MailAction(action='send', expected_version=1, confirmed=True))
        assert sent['status'] == outcome
        assert sent['sent_by'] == owner.user_id
        assert (await mail.action(db, owner, saved['id'], MailAction(action='send', expected_version=1, confirmed=True)))['status'] == outcome
        assert sender.call_count == 1
        assert sender.call_args.args[1]['message_id'].startswith('<oa-')


async def test_claims_prevent_duplicate_replies_and_stale_updates(oa_db, monkeypatch):
    async with oa_db() as db:
        owner, box = await setup(db, monkeypatch)
        other = await seed(db, tenant=owner.tenant_id, resources=['email'])
        db.add(PublicMailboxMember(mailbox_id=box['id'], user_id=other.user_id, can_process=True, can_send=True))
        await db.commit()
        row = await received(db, owner, monkeypatch)
        reply = await mail.save_draft(db, owner, draft(reply_to_id=row['id']))
        await db.commit()
        assert reply['reply_to_id'] == row['id']
        with pytest.raises(AppException) as conflict:
            await mail.save_draft(db, other, draft(reply_to_id=row['id']))
        assert conflict.value.http_status == 409
        with pytest.raises(AppException):
            await mail.action(db, owner, row['id'], MailAction(action='complete', expected_version=1))
        row = await mail.detail(db, owner, row['id'])
        await mail.action(db, owner, row['id'], MailAction(action='complete', expected_version=row['version']))
        await db.commit()
        assert (await mail.listing(db, owner, folder='pending'))['total'] == 0


async def test_draft_idempotency_fixed_sender_and_header_validation(oa_db, monkeypatch):
    async with oa_db() as db:
        owner, _ = await setup(db, monkeypatch)
        saved = await mail.save_draft(db, owner, draft())
        await db.commit()
        assert (await mail.save_draft(db, owner, draft()))['id'] == saved['id']
        assert saved['sender'] == 'office@example.com'
        with pytest.raises(AppException):
            await mail.save_draft(db, owner, draft(body='different'))
        for fields in [{'subject': 'bad\r\nBcc: evil@example.com'}, {'recipients': ['x@example.com\r\nBcc: evil@example.com']},
                       {'subject': 'bad\x00subject'}, {'body': 'bad\x00body'}]:
            with pytest.raises(ValidationError):
                draft(**fields)


async def test_members_preserve_manager_and_reject_foreign_users(oa_db, monkeypatch):
    async with oa_db() as db:
        owner, box = await setup(db, monkeypatch)
        other = await seed(db, tenant=owner.tenant_id, resources=['email'])
        foreign = await seed(db, resources=['email'])
        await db.commit()
        manager = dict(user_id=owner.user_id, can_manage=True, can_process=True, can_send=True)
        for members in [[dict(user_id=other.user_id)], [manager, dict(user_id=foreign.user_id)]]:
            with pytest.raises(AppException):
                await mail.save_members(db, owner, MailMembers(expected_revision=1, members=members))
        result = await mail.save_members(db, owner, MailMembers(expected_revision=1, members=[manager, dict(user_id=other.user_id)]))
        await db.commit()
        assert result['revision'] == 2
        assert (await mail.status(db, other))['authorized'] is True
        with pytest.raises(AppException):
            await mail.save_members(db, owner, MailMembers(expected_revision=1, members=[manager]))


async def test_mailbox_source_rechecks_membership_and_reuses_task_batch(oa_db, monkeypatch):
    from app.services import work_task_service as tasks
    async with oa_db() as db:
        owner, box = await setup(db, monkeypatch)
        row = await received(db, owner, monkeypatch)
        result = await mail.convert_task(db, owner, row['id'])
        await db.commit()
        assert (await mail.convert_task(db, owner, row['id'])) == result
        assert (await tasks.get_batch(db, owner, result['batch_id'])).source_type == 'email'
        membership = await db.get(PublicMailboxMember, (box['id'], owner.user_id))
        await db.delete(membership)
        await db.commit()
        with pytest.raises(AppException):
            await tasks.get_batch(db, owner, result['batch_id'])


async def test_direct_task_endpoint_cannot_bypass_processing_or_claim(oa_db, monkeypatch):
    from app.services import work_task_service as tasks
    from app.schemas.work_task import WorkTaskSourceInput
    async with oa_db() as db:
        owner, box = await setup(db, monkeypatch)
        reader = await seed(db, tenant=owner.tenant_id, resources=['email', 'work_task'])
        membership = PublicMailboxMember(mailbox_id=box['id'], user_id=reader.user_id)
        db.add(membership)
        await db.commit()
        row = await received(db, owner, monkeypatch)
        payload = WorkTaskSourceInput(source_type='email', source_id=row['id'], idempotency_key='direct')
        with pytest.raises(AppException):
            await tasks.create_batch(db, reader, payload)
        await db.rollback()
        await mail.convert_task(db, owner, row['id'])
        await db.commit()
        membership = await db.get(PublicMailboxMember, (box['id'], reader.user_id))
        membership.can_process = True
        await db.commit()
        with pytest.raises(AppException) as exc:
            await tasks.create_batch(db, reader, payload)
        assert exc.value.http_status == 409


async def test_network_binding_change_fails_closed(oa_db, monkeypatch):
    async with oa_db() as db:
        owner, _ = await setup(db, monkeypatch)
        receiver = stub_sync(monkeypatch)
        settings = mail.get_settings()
        settings.smtp_from = 'different@example.com'
        with pytest.raises(AppException):
            await mail.sync(db, owner)
        receiver.assert_not_called()


async def test_analysis_import_is_explicit_and_deduplicated(oa_db, monkeypatch):
    async with oa_db() as db:
        owner, _ = await setup(db, monkeypatch)
        row = await received(db, owner, monkeypatch)
        analyzer = AsyncMock()
        monkeypatch.setattr(mail.email_service, 'analyze', analyzer)
        result = await mail.import_analysis(db, owner, row['id'])
        await db.commit()
        assert (await mail.import_analysis(db, owner, row['id'])) == result
        analyzer.assert_awaited_once()
        assert (await mail.detail(db, owner, row['id']))['analysis_id'] == result['email_id']


async def test_simultaneous_send_only_calls_transport_once(oa_db, monkeypatch):
    import threading
    async with oa_db() as db:
        owner, _ = await setup(db, monkeypatch)
        saved = await mail.save_draft(db, owner, draft())
        await db.commit()
    entered, release = threading.Event(), threading.Event()
    def transport(*args):
        entered.set()
        assert release.wait(10)
        return 'ACCEPTED'
    sender = Mock(side_effect=transport)
    monkeypatch.setattr(mail.transport, 'send_message', sender)
    async def send():
        async with oa_db() as db:
            result = await mail.action(db, owner, saved['id'], MailAction(action='send', expected_version=1, confirmed=True))
            await db.commit()
            return result
    first = asyncio.create_task(send())
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        second = await asyncio.wait_for(send(), 5)
        assert second['status'] == 'SENDING'
    finally:
        release.set()
    assert (await first)['status'] == 'ACCEPTED'
    assert sender.call_count == 1


async def test_transport_receipt_survives_actor_revocation(oa_db, monkeypatch):
    import threading
    from sqlalchemy import update
    entered, release = threading.Event(), threading.Event()
    async with oa_db() as db:
        owner, _ = await setup(db, monkeypatch)
        saved = await mail.save_draft(db, owner, draft())
        await db.commit()
    def transport(*args):
        entered.set()
        assert release.wait(10)
        return 'ACCEPTED'
    monkeypatch.setattr(mail.transport, 'send_message', transport)
    async def send():
        async with oa_db() as db:
            return await mail.action(db, owner, saved['id'], MailAction(action='send', expected_version=1, confirmed=True))
    sending = asyncio.create_task(send())
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        async with oa_db() as db:
            await db.execute(update(OAUser).where(OAUser.id == owner.user_id).values(status='disabled'))
            await db.commit()
    finally:
        release.set()
    with pytest.raises(AppException):
        await sending
    async with oa_db() as db:
        row = await db.get(PublicMailMessage, saved['id'])
        assert row.status == 'ACCEPTED'


async def test_http_routes_auth_validation_and_member_isolation(oa_db, monkeypatch):
    import httpx
    from app.main import app
    from app.api.deps import get_current_user
    from app.db.session import get_db
    async with oa_db() as db:
        owner, _ = await setup(db, monkeypatch)
        outsider = await seed(db, tenant=owner.tenant_id, resources=['email'])
        await db.commit()
    async def database():
        async with oa_db() as db:
            yield db
    app.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/api/public-mail/status')).status_code == 401
            app.dependency_overrides[get_current_user] = lambda: owner
            result = await client.post('/api/public-mail/messages', json=draft().model_dump())
            assert result.status_code == 200, result.text
            value = result.json()['data']
            assert (await client.get('/api/public-mail/messages/' + value['id'])).json()['data']['body']
            assert (await client.get('/api/public-mail/messages?folder=other')).status_code == 422
            assert (await client.post('/api/public-mail/messages', json={**draft().model_dump(), 'recipients': ['bad\r\nBcc:x@test.com']})).status_code == 422
            app.dependency_overrides[get_current_user] = lambda: outsider
            assert (await client.get('/api/public-mail/messages/' + value['id'])).status_code == 403
            assert (await client.get('/api/public-mail/members')).status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


async def test_real_route_admission_without_ai_still_checks_email_grant(oa_db, monkeypatch):
    from starlette.requests import Request
    from app.api import deps
    from app.core import config
    async with oa_db() as db:
        owner, _ = await setup(db, monkeypatch)
        no_email = await seed(db, tenant=owner.tenant_id, resources=['organization'])
        await db.commit()
        settings = config.get_settings().model_copy(update={'ai_enabled': False})
        monkeypatch.setattr(config, 'get_settings', lambda: settings)
        request = Request({'type': 'http', 'method': 'GET', 'path': '/api/public-mail/status', 'headers': []})
        monkeypatch.setattr(deps, '_ctx_user', lambda: owner)
        assert (await deps.get_current_user(request, db)).user_id == owner.user_id
        monkeypatch.setattr(deps, '_ctx_user', lambda: no_email)
        with pytest.raises(AppException) as denied:
            await deps.get_current_user(request, db)
        assert denied.value.http_status == 403


async def test_ai_disabled_blocks_conversions_but_not_normal_mail(oa_db, monkeypatch):
    from app.core import config
    async with oa_db() as db:
        owner, _ = await setup(db, monkeypatch)
        row = await received(db, owner, monkeypatch)
        settings = config.get_settings().model_copy(update={'ai_enabled': False})
        monkeypatch.setattr(config, 'get_settings', lambda: settings)
        assert (await mail.detail(db, owner, row['id']))['body']
        for convert in (mail.import_analysis, mail.convert_task):
            with pytest.raises(AppException) as unavailable:
                await convert(db, owner, row['id'])
            assert unavailable.value.http_status == 503
