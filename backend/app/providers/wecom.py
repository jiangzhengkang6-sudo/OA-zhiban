"""WeCom group webhook: generic reminders, strict endpoint, no secret logging."""
import hashlib
import http.client
import json
from urllib.parse import parse_qs, urlsplit

from ..core.config import get_settings


def endpoint(settings):
    value = settings.wecom_webhook_url.get_secret_value()
    try:
        parts = urlsplit(value)
        query = parse_qs(parts.query, strict_parsing=True)
        if (parts.scheme != 'https' or parts.netloc != 'qyapi.weixin.qq.com'
                or parts.path != '/cgi-bin/webhook/send' or parts.fragment
                or set(query) != {'key'} or len(query['key']) != 1
                or not query['key'][0] or any(c.isspace() for c in value)):
            return None
    except ValueError:
        return None
    return parts.path + '?' + parts.query


def destination(settings, tenant, department):
    if (not settings.wecom_enabled or not tenant or not department
            or tenant != settings.wecom_tenant_id or department != settings.wecom_department_id
            or not endpoint(settings)):
        return None
    key = parse_qs(urlsplit(settings.wecom_webhook_url.get_secret_value()).query)['key'][0]
    return hashlib.sha256(('qyapi.weixin.qq.com:group-robot:' + key).encode()).hexdigest()


def send(claim):
    settings = get_settings()
    path = endpoint(settings)
    # A claim cannot silently follow a reconfigured robot.
    if (not path or not settings.wecom_enabled or claim.get('destination_hash') !=
            destination(settings, claim.get('tenant_id'), claim.get('department_id'))):
        return 'PERMANENT'
    content = claim['body']
    if len(content.encode('utf-8')) > 2048:
        return 'PERMANENT'
    connection = http.client.HTTPSConnection('qyapi.weixin.qq.com', timeout=settings.wecom_timeout_seconds)
    started = False
    try:
        connection.connect()
        started = True
        connection.request('POST', path, json.dumps({'msgtype': 'text', 'text': {'content': content}},
            ensure_ascii=False).encode('utf-8'), {'Content-Type': 'application/json; charset=utf-8'})
        response = connection.getresponse()
        if response.status == 429:
            return 'TEMPORARY'
        if response.status >= 500:
            return 'UNKNOWN'
        if not 200 <= response.status < 300:
            return 'PERMANENT'
        raw = response.read(8193)
        if len(raw) > 8192:
            return 'UNKNOWN'
        data = json.loads(raw)
        code = data.get('errcode') if isinstance(data, dict) else None
        if type(code) is not int:
            return 'UNKNOWN'
        if code == 0:
            return 'ACCEPTED'
        return 'TEMPORARY' if code in {-1, 45009} else 'PERMANENT'
    except Exception:
        # Once request transmission starts, a timeout cannot prove non-delivery.
        return 'UNKNOWN' if started else 'TEMPORARY'
    finally:
        connection.close()
