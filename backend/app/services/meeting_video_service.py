"""Tencent room control and per-member admission. Signing keys never leave the server."""
import asyncio
import base64
import hashlib
import hmac
import http.client
import json
import logging
import secrets
import socket
import time
import zlib
from datetime import datetime, timezone
from urllib.parse import urlencode

from sqlalchemy import select
from ..core import config
from ..core.errors import dependency_failed
from ..models.identity import OAUser
from ..models.oa_meeting import OAMeeting
from .oa_access_service import invalid

logger = logging.getLogger(__name__)


def settings():
    value = config.get_settings()
    if not value.trtc_sdk_app_id or not value.trtc_sdk_secret_key.get_secret_value():
        raise dependency_failed('视频会议尚未配置，请联系管理员')
    return value


def user_sig(user_id, *, issued_at=None, expires=None):
    value = settings()
    issued_at = int(time.time()) if issued_at is None else issued_at
    expires = value.trtc_user_sig_expire_seconds if expires is None else expires
    content = (f'TLS.identifier:{user_id}\nTLS.sdkappid:{value.trtc_sdk_app_id}\n'
               f'TLS.time:{issued_at}\nTLS.expire:{expires}\n')
    signature = base64.b64encode(hmac.new(value.trtc_sdk_secret_key.get_secret_value().encode(),
        content.encode(), hashlib.sha256).digest()).decode()
    payload = {'TLS.ver': '2.0', 'TLS.identifier': user_id, 'TLS.sdkappid': value.trtc_sdk_app_id,
        'TLS.expire': expires, 'TLS.time': issued_at, 'TLS.sig': signature}
    return base64.b64encode(zlib.compress(json.dumps(payload, separators=(',', ':')).encode())).decode().translate(
        str.maketrans({'+': '*', '/': '-', '=': '_'}))


def account_id(tenant_id, user_id):
    # Tencent IM's default Identifier limit is 32 bytes.
    return 'oa_' + hashlib.sha256(json.dumps([tenant_id, user_id]).encode()).hexdigest()[:29]


def room_id(row):
    return 'oa_' + hashlib.sha256(json.dumps([row.tenant_id, row.id, row.invitation_version]).encode()).hexdigest()[:40]


def room_password(row):
    # RoomKit UserSig authenticates the account, while this password gates this room.
    digest = hmac.new(settings().trtc_sdk_secret_key.get_secret_value().encode(),
        ('meeting-password:' + room_id(row)).encode(), hashlib.sha256).digest()
    return f'{int.from_bytes(digest[:4], "big") % 1_000_000:06d}'


def _post(path, payload):
    # stdlib HTTPS does not log the credential-bearing URL (unlike HTTP client INFO logs).
    connection = http.client.HTTPSConnection('console.tim.qq.com', timeout=12)
    try:
        connection.request('POST', path, body=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        body = response.read(65537)
        if response.status != 200 or len(body) > 65536:
            raise ValueError('invalid response')
        return json.loads(body)
    finally:
        connection.close()


async def request(action, payload, *, accepted=()):
    value = settings()
    params = urlencode(dict(sdkappid=value.trtc_sdk_app_id, identifier=value.trtc_admin_user_id,
        usersig=user_sig(value.trtc_admin_user_id, expires=300), random=secrets.randbits(32), contenttype='json'))
    namespace = 'im_open_login_svc' if action == 'account_import' else 'room_engine_http_srv'
    try:
        for attempt in range(2):
            try:
                data = await asyncio.to_thread(_post, f'/v4/{namespace}/{action}?{params}', payload)
                break
            except socket.gaierror:
                # DNS failed before dispatch. Retrying other transport failures
                # could repeat a cloud write whose response was lost.
                if attempt == 1:
                    raise
                logger.warning('Tencent video DNS retry: action=%s', action)
                await asyncio.sleep(0.25)
        code = data['ErrorCode']
        if type(code) is not int:
            raise ValueError('invalid error code')
        if code == 0 and data.get('ActionStatus') != 'OK':
            raise ValueError('failed action status')
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as error:
        logger.warning('Tencent video transport failed: action=%s error_type=%s', action, type(error).__name__)
        if isinstance(error, socket.gaierror):
            raise dependency_failed('腾讯视频会议域名解析失败，请检查服务器网络后重试') from None
        raise dependency_failed('腾讯视频会议暂时不可用，请稍后重试') from None
    if code != 0 and code not in accepted:
        messages = {
            70001: '腾讯视频会议签名校验失败，请核对应用与密钥',
            70003: '腾讯视频会议签名已过期，请检查服务器时间',
            100006: '腾讯视频会议管理权限不足，请核对管理员账号',
            100007: '腾讯视频会议套餐暂不可用，请核对组件权益',
        }
        raise dependency_failed(messages.get(code, '腾讯视频会议操作失败，请稍后重试'), detail={'provider_code': code})
    return data


async def ensure_room(row):
    rid, owner = room_id(row), account_id(row.tenant_id, row.host_id)
    result = await request('get_room_info', {'RoomId': rid}, accepted=(100004,))
    if result['ErrorCode'] == 100004:
        if row.video_room_created:
            raise invalid('视频房间已关闭，请主持人结束本次会议；如需继续，请另行安排会议')
        await request('account_import', {'Identifier': owner})
        await request('create_room', {'RoomInfo': {
            'RoomId': rid, 'RoomName': row.title.encode()[:100].decode('utf-8', errors='ignore'),
            'RoomType': 'Conference', 'Owner_Account': owner,
            'IsPasswordEnabled': True, 'Password': room_password(row),
            'IsCloudRecordingDisabled': True, 'IsSeatEnabled': False,
        }}, accepted=(100003, 100010))
        result = await request('get_room_info', {'RoomId': rid})
    info = result.get('Response', {}).get('RoomInfo', {})
    if info.get('RoomId') != rid or info.get('Owner_Account') != owner or info.get('IsPasswordEnabled') is not True:
        raise dependency_failed('视频房间信息校验失败，请联系管理员')
    row.video_room_created = True


async def close_room(row):
    await request('destroy_room', {'RoomId': room_id(row)}, accepted=(100004,))


async def admission(db, actor, meeting_id):
    from .meeting_management_service import access
    from .identity_service import lock_tenant
    actor, row = await access(db, actor, meeting_id)
    # Meeting commands take the tenant gate before meeting/user locks. Admission
    # must use the same order, including the final identity check at commit.
    await lock_tenant(db, actor.tenant_id)
    # Serialize admission against end/cancel without requiring attendee write permission.
    row = await db.scalar(select(OAMeeting).where(OAMeeting.id == row.id,
        OAMeeting.tenant_id == actor.tenant_id).with_for_update().execution_options(populate_existing=True))
    actor, row = await access(db, actor, meeting_id)
    if not row.video_enabled:
        raise invalid('本次会议未启用视频会议')
    if row.state != 'IN_PROGRESS':
        raise invalid('会议开始后才可入会，已结束或取消的会议不可入会')
    await ensure_room(row)
    uid = account_id(actor.tenant_id, actor.user_id)
    await request('account_import', {'Identifier': uid}, accepted=(100003, 100010))
    user = await db.get(OAUser, actor.user_id)
    value = settings()
    now = int(time.time())
    await db.flush()
    return dict(sdkAppId=value.trtc_sdk_app_id, userId=uid, userName=user.display_name,
        userSig=user_sig(uid, issued_at=now), roomId=room_id(row), password=room_password(row),
        expiresAt=datetime.fromtimestamp(now + value.trtc_user_sig_expire_seconds, timezone.utc).isoformat())
