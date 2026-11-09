"""Check local ASR configuration without network requests or secret output."""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import Settings


def public_callback_url(value, api_prefix):
    try:
        url = urlsplit(value)
        host = (url.hostname or '').lower().rstrip('.')
        url.port  # Validate malformed or out-of-range ports without resolving DNS.
        if (url.scheme != 'https' or not host or url.username or url.password or
                url.fragment or url.query or url.path != api_prefix.rstrip('/') +
                '/meeting-transcriptions/callback/trtc'):
            return False
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.test', '.invalid', '.example')):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return '.' in host
    except ValueError:
        return False


def check_configuration(settings):
    checks = []

    def add(name, valid, hint):
        checks.append(dict(name=name, passed=bool(valid), hint='' if valid else hint))

    add('AI_ENABLED', settings.ai_enabled, '需要启用智能功能。')
    add('TRTC_SDK_APP_ID', settings.trtc_sdk_app_id > 0, '保留现有视频应用 SDKAppID。')
    for name in ['trtc_sdk_secret_key', 'meeting_transcription_secret_id', 'meeting_transcription_secret_key']:
        add(name.upper(), getattr(settings, name).get_secret_value().strip(), '请在私有配置文件填写，不要发送到聊天或文档。')
    add('MEETING_TRANSCRIPTION_CALLBACK_KEY',
        re.fullmatch(r'[A-Za-z0-9]{16,32}', settings.meeting_transcription_callback_key.get_secret_value()),
        '填写 16 至 32 位英文字母和数字，与腾讯控制台的回调密钥一致。')
    add('MEETING_TRANSCRIPTION_CALLBACK_URL',
        public_callback_url(settings.meeting_transcription_callback_url, settings.api_prefix),
        '填写公网 HTTPS 地址，路径为 ' + settings.api_prefix.rstrip('/') + '/meeting-transcriptions/callback/trtc。')
    add('MEETING_TRANSCRIPTION_REGION', settings.meeting_transcription_region.strip(), '填写腾讯云 API 地域。')
    add('MEETING_TRANSCRIPTION_LANGUAGE', settings.meeting_transcription_language.strip(), '填写 ASR 引擎。')
    ready = all(check['passed'] for check in checks)
    return dict(checks=checks, ready_to_enable=ready,
        enabled=settings.meeting_transcription_enabled, locally_enabled=ready and settings.meeting_transcription_enabled,
        network_requests=False, cloud_acceptance=False,
        note='仅检查本地配置格式；不验证密钥有效性、控制台配置、DNS、证书、回调可达性或 ASR 额度。')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path(__file__).resolve().parents[1] / '.env',
        help='Defaults to backend/.env, independent of current directory. Process environment overrides this file.')
    options = parser.parse_args(argv)
    if not options.env_file.is_file():
        report = dict(error='env_file_missing', network_requests=False)
    else:
        try:
            report = check_configuration(Settings(_env_file=options.env_file))
        except ValidationError as exc:
            # Pydantic errors can contain raw credentials; print field names and error codes only.
            report = dict(error='invalid_settings', fields=[dict(name='.'.join(map(str, item['loc'])),
                code=item['type']) for item in exc.errors()], network_requests=False)
        except (OSError, UnicodeError):
            report = dict(error='env_file_unreadable', network_requests=False)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get('ready_to_enable') else 1


if __name__ == '__main__':
    raise SystemExit(main())
