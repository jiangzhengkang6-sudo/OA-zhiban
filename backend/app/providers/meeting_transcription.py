"""Tencent Cloud 2.0 transcription API. SDK handles TC3 signing, never retries create."""
import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlsplit
from ..core import config
from ..core.errors import dependency_failed
from ..services.oa_access_service import denied, invalid


def configured():
    s = config.get_settings()
    try:
        url = urlsplit(s.meeting_transcription_callback_url)
        url.port  # Invalid configuration must disable the feature rather than break status requests.
    except ValueError:
        return False
    key = s.meeting_transcription_callback_key.get_secret_value()
    return bool(s.ai_enabled and s.meeting_transcription_enabled and s.trtc_sdk_app_id and
        s.trtc_sdk_secret_key.get_secret_value() and s.meeting_transcription_secret_id.get_secret_value() and
        s.meeting_transcription_secret_key.get_secret_value() and re.fullmatch(r'[A-Za-z0-9]{16,32}', key) and
        url.scheme == 'https' and url.hostname and not url.username and not url.password and not url.fragment)


async def request(action, payload):
    s = config.get_settings()
    if (action=='CreateCloudTranscription' and not configured()) or not (
            s.meeting_transcription_secret_id.get_secret_value() and s.meeting_transcription_secret_key.get_secret_value()):
        raise dependency_failed('会议转写尚未完成服务端配置')
    def invoke():
        from tencentcloud.common.credential import Credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.trtc.v20190722 import models, trtc_client
        profile = ClientProfile()
        profile.httpProfile = HttpProfile(reqTimeout=6)
        client = trtc_client.TrtcClient(Credential(s.meeting_transcription_secret_id.get_secret_value(),
            s.meeting_transcription_secret_key.get_secret_value()), s.meeting_transcription_region, profile)
        req = getattr(models, action + 'Request')()
        req.from_json_string(json.dumps(payload))
        return json.loads(getattr(client, action)(req).to_json_string())
    return await asyncio.to_thread(invoke)


def verify_callback(raw, sign, app_id):
    s = config.get_settings()
    key = s.meeting_transcription_callback_key.get_secret_value()
    expected = base64.b64encode(hmac.new(key.encode(), raw, hashlib.sha256).digest()).decode()
    if not key or not hmac.compare_digest(expected.encode(), sign.encode()) or str(s.trtc_sdk_app_id) != app_id:
        raise denied()
    try:
        event = json.loads(raw)
        if (not isinstance(event, dict) or event['EventGroupId'] != 14 or
                type(event['CallbackTs']) not in {int, float} or
                not abs(time.time()*1000 - event['CallbackTs']) <= 300000):
            raise ValueError()
        if event['EventType'] not in {1401,1402,1403,1404} or not isinstance(event['EventInfo'], dict):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise invalid('转写回调内容不合法或已过期') from None
    return event
