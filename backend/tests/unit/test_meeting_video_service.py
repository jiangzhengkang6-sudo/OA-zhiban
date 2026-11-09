from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import socket
import pytest
from app.core.errors import AppException
from app.services import meeting_video_service as video


async def test_transport_failure_logs_only_action_and_error_type(monkeypatch, caplog):
    monkeypatch.setattr(video, 'settings', lambda: SimpleNamespace(trtc_sdk_app_id=42, trtc_admin_user_id='administrator'))
    monkeypatch.setattr(video, 'user_sig', lambda *args, **kwargs: 'private-test-signature')
    def failed(path, payload):
        raise TimeoutError('private-test-signature')
    monkeypatch.setattr(video, '_post', failed)
    with pytest.raises(AppException, match='腾讯视频会议暂时不可用'):
        await video.request('get_room_info', {'RoomId': 'test'})
    assert 'get_room_info' in caplog.text and 'TimeoutError' in caplog.text
    assert 'private-test-signature' not in caplog.text


async def test_transient_dns_failure_retries_before_the_request_is_sent(monkeypatch, caplog):
    from unittest.mock import Mock
    monkeypatch.setattr(video, 'settings', lambda: SimpleNamespace(trtc_sdk_app_id=42, trtc_admin_user_id='administrator'))
    monkeypatch.setattr(video, 'user_sig', lambda *args, **kwargs: 'private-test-signature')
    post = Mock(side_effect=[socket.gaierror(11002, 'temporary DNS failure'), {'ErrorCode': 0, 'ActionStatus': 'OK'}])
    monkeypatch.setattr(video, '_post', post)
    monkeypatch.setattr(video.asyncio, 'sleep', AsyncMock())
    assert (await video.request('get_room_info', {'RoomId': 'test'}))['ErrorCode'] == 0
    assert post.call_count == 2
    assert 'private-test-signature' not in caplog.text


async def test_persistent_dns_failure_is_bounded_and_explained(monkeypatch, caplog):
    from unittest.mock import Mock
    monkeypatch.setattr(video, 'settings', lambda: SimpleNamespace(trtc_sdk_app_id=42, trtc_admin_user_id='administrator'))
    monkeypatch.setattr(video, 'user_sig', lambda *args, **kwargs: 'private-test-signature')
    post = Mock(side_effect=socket.gaierror(11001, 'private-test-signature'))
    monkeypatch.setattr(video, '_post', post)
    monkeypatch.setattr(video.asyncio, 'sleep', AsyncMock())
    with pytest.raises(AppException, match='域名解析失败'):
        await video.request('get_room_info', {'RoomId': 'test'})
    assert post.call_count == 2
    assert 'private-test-signature' not in caplog.text


async def test_timeout_does_not_retry_a_potentially_applied_cloud_write(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(video, 'settings', lambda: SimpleNamespace(trtc_sdk_app_id=42, trtc_admin_user_id='administrator'))
    monkeypatch.setattr(video, 'user_sig', lambda *args, **kwargs: 'private-test-signature')
    post = Mock(side_effect=TimeoutError('timeout'))
    monkeypatch.setattr(video, '_post', post)
    with pytest.raises(AppException):
        await video.request('destroy_room', {'RoomId': 'test'})
    assert post.call_count == 1


def test_user_sig_is_signed_and_scoped_to_configured_app(monkeypatch):
    from app.core import config
    settings = SimpleNamespace(trtc_sdk_app_id=1600168994, trtc_sdk_secret_key=SimpleNamespace(get_secret_value=lambda: 'a'*64),
        trtc_user_sig_expire_seconds=600, trtc_admin_user_id='administrator')
    monkeypatch.setattr(config, 'get_settings', lambda: settings)
    signature = video.user_sig('oa_member', issued_at=1_800_000_000)
    assert signature and signature != 'a'*64
    assert video.account_id('tenant', 'member').startswith('oa_')
    assert len(video.room_id(SimpleNamespace(tenant_id='tenant', id='meeting', invitation_version=1))) == 43


def test_room_password_is_stable_six_digit_numeric_value(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config, 'get_settings', lambda: SimpleNamespace(
        trtc_sdk_app_id=1600168994,
        trtc_sdk_secret_key=SimpleNamespace(get_secret_value=lambda: 'a' * 64),
    ))
    meeting = SimpleNamespace(tenant_id='tenant', id='meeting', invitation_version=1)

    password = video.room_password(meeting)

    assert password == video.room_password(meeting)
    assert len(password) == 6
    assert password.isascii() and password.isdigit()


async def test_admission_requires_participant_active_video_and_started_room(monkeypatch):
    from app.services import meeting_management_service
    from unittest.mock import MagicMock
    actor = SimpleNamespace(tenant_id='tenant', user_id='member')
    row = SimpleNamespace(tenant_id='tenant', id=uuid4().hex, invitation_version=1, host_id='host', title='video',
        video_enabled=True, state='SCHEDULED', video_room_created=False)
    monkeypatch.setattr(meeting_management_service, 'access', AsyncMock(return_value=(actor, row)))
    db = MagicMock()
    db.scalar = AsyncMock(return_value=row)
    db.execute = AsyncMock()
    with pytest.raises(AppException, match='会议开始后才可入会'):
        await video.admission(db, actor, row.id)
    row.state='IN_PROGRESS'
    row.video_enabled=False
    with pytest.raises(AppException, match='未启用视频会议'):
        await video.admission(db, actor, row.id)


async def test_admission_imports_the_admitted_member_before_issuing_sig(monkeypatch):
    from app.services import meeting_management_service
    from unittest.mock import MagicMock
    actor = SimpleNamespace(tenant_id='tenant', user_id='attendee')
    row = SimpleNamespace(tenant_id='tenant', id=uuid4().hex, invitation_version=1, host_id='host', title='video',
        video_enabled=True, state='IN_PROGRESS', video_room_created=True)
    monkeypatch.setattr(meeting_management_service, 'access', AsyncMock(return_value=(actor, row)))
    monkeypatch.setattr(video, 'ensure_room', AsyncMock())
    imported = AsyncMock()
    monkeypatch.setattr(video, 'request', imported)
    monkeypatch.setattr(video, 'account_id', lambda tenant_id, user_id: 'oa_attendee')
    monkeypatch.setattr(video, 'user_sig', lambda uid, issued_at: 'short-lived-sig')
    monkeypatch.setattr(video, 'room_id', lambda meeting: 'room-id')
    monkeypatch.setattr(video, 'room_password', lambda meeting: '123456')
    monkeypatch.setattr(video, 'settings', lambda: SimpleNamespace(trtc_sdk_app_id=42,
        trtc_user_sig_expire_seconds=600))
    db = MagicMock()
    db.scalar = AsyncMock(return_value=row)
    db.get = AsyncMock(return_value=SimpleNamespace(display_name='attendee'))
    db.execute = AsyncMock()
    db.flush = AsyncMock()

    credentials = await video.admission(db, actor, row.id)

    imported.assert_awaited_once_with('account_import', {'Identifier': 'oa_attendee'}, accepted=(100003, 100010))
    assert credentials['userId'] == 'oa_attendee'
