"""Independent, tenant-bound watchdog. State survives database/application outages."""
import asyncio
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text

CHECKS = {
    'application': '后端服务', 'database': '数据库', 'notification_backlog': '通知积压',
    'backup': '备份任务', 'text_model': '主文字模型', 'standby_model': '备用文字模型',
    'embedding': '嵌入模型',
    'critical_errors': '严重运行错误',
    'log_keywords': '日志关键字',
}
MESSAGES = {
    'healthy': '检查通过', 'unavailable': '依赖暂不可用', 'backlog': '存在超时待投递或待核对通知',
    'missing': '尚无备份任务记录', 'failed': '最近一次备份失败', 'overdue': '成功备份已超期',
    'running': '备份正在执行', 'timeout': '备份执行超时', 'invalid': '备份记录无效',
    'disabled': '未启用主动探测', 'blocked': '数据库不可用，无法检查通知队列',
    'recent_errors': '最近五分钟有严重运行错误', 'no_errors': '最近五分钟未记录严重运行错误',
    'no_error_receipt': '尚无运行日志采集记录', 'error_receipt_invalid': '运行日志采集记录无效',
    'log_disabled': '未配置日志文件', 'log_unreadable': '日志文件不可读取，请核对配置和权限',
    'log_invalid': '日志扫描记录无效', 'log_matched': '最近五分钟命中日志关键字',
    'log_catching_up': '正在追赶日志扫描进度', 'log_clear': '最近五分钟未命中日志关键字',
}


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.astimezone(timezone.utc).isoformat()


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Timezone required')
    return parsed.astimezone(timezone.utc)


def read_json(path):
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('State too large')
    return json.loads(path.read_text(encoding='utf-8'))


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def exclusive(path):
    """OS releases the lock on process death; a stale lock file is harmless."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def result(key, status, code, **details):
    return dict(key=key, name=CHECKS[key], status=status, code=code,
                message=MESSAGES[code], **details)


def backup_check(settings, now):
    try:
        path = Path(settings.ops_state_dir) / 'backup.json'
        if not path.exists():
            return result('backup', 'FAIL', 'missing')
        data = read_json(path)
        if data['version'] != 1 or data['tenant_id'] != settings.auth_tenant_id or data['status'] not in {'RUNNING', 'SUCCESS', 'FAILED'}:
            raise ValueError('Invalid receipt')
        started = timestamp(data['started_at'])
        if started > now + timedelta(seconds=30):
            raise ValueError('Future receipt')
        if data['status'] == 'FAILED':
            return result('backup', 'FAIL', 'failed')
        if data['status'] == 'RUNNING':
            timed_out = (now-started).total_seconds() > settings.ops_backup_max_runtime_seconds
            return result('backup', 'FAIL' if timed_out else 'WARN', 'timeout' if timed_out else 'running')
        completed = timestamp(data['completed_at'])
        if (completed < started or completed > now + timedelta(seconds=30)
                or not re.fullmatch('[a-f0-9]{64}', str(data.get('artifact_sha256', '')))
                or type(data.get('artifact_bytes')) is not int or data['artifact_bytes'] <= 0):
            raise ValueError('Invalid success receipt')
        overdue = (now-completed).total_seconds() > settings.ops_backup_max_age_hours * 3600
        return result('backup', 'FAIL' if overdue else 'PASS', 'overdue' if overdue else 'healthy', last_success_at=stamp(completed))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return result('backup', 'FAIL', 'invalid')


def database_checks(settings, now):
    engine = create_engine(settings.database_sync_url, pool_pre_ping=True,
        connect_args={'connect_timeout': int(settings.ops_probe_timeout_seconds),
                      'options': '-c statement_timeout=10000'})
    try:
        with engine.connect() as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            db.execute(text('SELECT 1'))
            cutoff = now-timedelta(seconds=settings.ops_backlog_age_seconds)
            deliveries = db.execute(text('''SELECT count(*) FROM oa_notification_delivery
                WHERE tenant_id=:tenant AND
                ((state IN ('PENDING','PROCESSING') AND created_at<=:cutoff)
                 OR state IN ('FAILED','UNKNOWN'))'''), dict(tenant=settings.auth_tenant_id, cutoff=cutoff)).scalar_one()
            outbox = db.execute(text('''SELECT count(*) FROM oa_workflow_outbox
                WHERE tenant_id=:tenant AND
                ((status='PENDING' AND created_at<=:cutoff) OR status='FAILED')'''),
                dict(tenant=settings.auth_tenant_id, cutoff=cutoff)).scalar_one()
            count = deliveries + outbox
            return [result('database', 'PASS', 'healthy'),
                    result('notification_backlog', 'FAIL' if count else 'PASS',
                           'backlog' if count else 'healthy', count=count)]
    finally:
        engine.dispose()


def critical_error_check(settings, now):
    path = Path(settings.ops_state_dir) / 'errors.json'
    try:
        if not path.exists():
            return result('critical_errors', 'WARN', 'no_error_receipt')
        receipt = read_json(path)
        if receipt['tenant_id'] != settings.auth_tenant_id or receipt['version'] != 1:
            raise ValueError('Invalid receipt')
        started = timestamp(receipt['started_at'])
        last = timestamp(receipt['last_error_at']) if receipt['last_error_at'] else None
        if started > now + timedelta(seconds=30) or last and last > now + timedelta(seconds=30):
            raise ValueError('Future receipt')
        recent = last is not None and (now-last).total_seconds() <= 300
        return result('critical_errors', 'FAIL' if recent else 'PASS', 'recent_errors' if recent else 'no_errors')
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return result('critical_errors', 'WARN', 'error_receipt_invalid')


async def collect(settings, *, now=None):
    from .log_keywords import scan
    now = now or utcnow()
    async def application():
        try:
            async with httpx.AsyncClient(timeout=settings.ops_probe_timeout_seconds, follow_redirects=False, trust_env=False) as client:
                response = await client.get(settings.ops_health_url)
                if response.status_code != 200 or response.json().get('status') != 'ok':
                    raise ValueError('Health check failed')
            return result('application', 'PASS', 'healthy')
        except Exception:
            return result('application', 'FAIL', 'unavailable')

    async def database():
        try:
            return await asyncio.to_thread(database_checks, settings, now)
        except Exception:
            return [result('database', 'FAIL', 'unavailable'), result('notification_backlog', 'WARN', 'blocked')]

    async def model(key, provider):
        if not settings.ai_enabled or not settings.ops_model_probes_enabled or provider in {'mock', 'none'}:
            return result(key, 'WARN', 'disabled')
        try:
            from .live_services import text_probe, embedding_probe
            await asyncio.wait_for(embedding_probe(settings) if key == 'embedding' else text_probe(provider),
                                   timeout=settings.ops_probe_timeout_seconds)
            return result(key, 'PASS', 'healthy')
        except Exception:
            return result(key, 'FAIL', 'unavailable')

    app_check, db_checks, primary, standby, embedding, logs = await asyncio.gather(application(), database(),
        model('text_model', settings.llm_provider), model('standby_model', settings.llm_fallback_provider),
        model('embedding', settings.embedding_provider), asyncio.to_thread(scan, settings, now))
    return [app_check, *db_checks, backup_check(settings, now), primary, standby, embedding,
            critical_error_check(settings, now), logs]


def new_state(settings):
    return dict(version=1, tenant_id=settings.auth_tenant_id, checked_at=None, checks=[], incidents=[])


def load_state(settings):
    path = Path(settings.ops_state_dir) / 'state.json'
    if not path.exists():
        return new_state(settings)
    data = read_json(path)
    if not isinstance(data, dict) or data.get('version') != 1 or data.get('tenant_id') != settings.auth_tenant_id:
        raise ValueError('Monitor state invalid')
    if data['checked_at'] is not None:
        timestamp(data['checked_at'])
    if not isinstance(data['checks'], list) or len(data['checks']) > len(CHECKS):
        raise ValueError('Invalid checks')
    for check in data['checks']:
        if check['key'] not in CHECKS or check['status'] not in {'PASS', 'WARN', 'FAIL'} or check['code'] not in MESSAGES:
            raise ValueError('Invalid check')
        if 'count' in check and (type(check['count']) is not int or check['count'] < 0):
            raise ValueError('Invalid count')
        if 'last_success_at' in check:
            timestamp(check['last_success_at'])
    if not isinstance(data['incidents'], list) or len(data['incidents']) > 100 + len(CHECKS):
        raise ValueError('Invalid incidents')
    active = set()
    identifiers = set()
    for row in data['incidents']:
        if row['key'] not in CHECKS or not re.fullmatch('[a-f0-9]{32}', row['id']) or row['id'] in identifiers:
            raise ValueError('Invalid incident')
        identifiers.add(row['id'])
        for field in ('opened_at', 'last_seen_at', 'resolved_at'):
            if row[field] is not None:
                timestamp(row[field])
        if row['resolved_at'] is None:
            if row['key'] in active:
                raise ValueError('Duplicate active incident')
            active.add(row['key'])
        if row.get('code') not in MESSAGES or not isinstance(row['deliveries'], dict):
            raise ValueError('Invalid incident details')
        for key, delivery in row['deliveries'].items():
            if key not in {p+':'+c for p in ('failure', 'recovery') for c in ('smtp','wecom')} or delivery['status'] not in {'ACCEPTED','TEMPORARY','PERMANENT','UNKNOWN'}:
                raise ValueError('Invalid delivery')
            timestamp(delivery['attempted_at'])
            if type(delivery.get('attempt_count', 1)) is not int or not 1 <= delivery.get('attempt_count', 1) <= 3:
                raise ValueError('Invalid attempt count')
    return data


def reconcile(state, checks, now):
    by_key = {r['key']: r for r in state['incidents'] if r['resolved_at'] is None}
    for check in checks:
        row = by_key.get(check['key'])
        if check['status'] == 'FAIL':
            if row is None:
                row = dict(id=uuid4().hex, key=check['key'], name=check['name'],
                           opened_at=stamp(now), last_seen_at=stamp(now), resolved_at=None,
                           message=check['message'], deliveries={})
                state['incidents'].append(row)
            row.update(last_seen_at=stamp(now), message=check['message'], code=check['code'])
        elif check['status'] == 'PASS' and row:
            row.update(resolved_at=stamp(now), last_seen_at=stamp(now))
    # Retain all unresolved incidents and the latest 100 resolved incidents.
    active = [r for r in state['incidents'] if r['resolved_at'] is None]
    resolved = [r for r in state['incidents'] if r['resolved_at'] is not None][-100:]
    state.update(checked_at=stamp(now), checks=checks, incidents=resolved+active)


def alert_claims(settings, row, phase):
    body = f"OA 运行告警{'恢复' if phase == 'recovery' else ''}：{CHECKS[row['key']]}。请由管理员登录系统核对。"
    if settings.smtp_enabled and settings.smtp_host and settings.smtp_from and settings.ops_alert_email_to.strip():
        yield 'smtp', dict(recipient=settings.ops_alert_email_to.strip(),
            message_id=f"<oa-ops-{row['id']}-{phase}@oa.local>", body=body)
    from ..providers.wecom import destination
    fingerprint = destination(settings, settings.auth_tenant_id, settings.wecom_department_id)
    if fingerprint:
        yield 'wecom', dict(tenant_id=settings.auth_tenant_id, department_id=settings.wecom_department_id,
                           destination_hash=fingerprint, body=body)


async def tick(settings, *, now=None, checks=None, senders=None):
    """Persist intent before IO. A crash/ambiguous send is never retried automatically."""
    now = now or utcnow()
    root = Path(settings.ops_state_dir)
    with exclusive(root / 'monitor.lock'):
        state = load_state(settings)
        checks = checks if checks is not None else await collect(settings, now=now)
        reconcile(state, checks, now)
        atomic_json(root / 'state.json', state)
        if not settings.ops_alert_delivery_enabled:
            return state
        from ..providers.smtp import send as smtp_send
        from ..providers.wecom import send as wecom_send
        senders = senders or {'smtp': smtp_send, 'wecom': wecom_send}
        slots = asyncio.Semaphore(8)

        async def deliver(row, phase, channel, claim):
            async with slots:
                key = phase + ':' + channel
                attempts = row['deliveries'].get(key, {}).get('attempt_count', 0) + 1
                target = claim.get('destination_hash') or hashlib.sha256(claim['recipient'].encode()).hexdigest()
                row['deliveries'][key] = dict(status='UNKNOWN', attempted_at=stamp(now), attempt_count=attempts, target_hash=target)
                atomic_json(root / 'state.json', state)
                try:
                    status = await asyncio.wait_for(asyncio.to_thread(senders[channel], claim), timeout=20)
                except Exception:
                    status = 'UNKNOWN'
                row['deliveries'][key]['status'] = status if status in {'ACCEPTED','TEMPORARY','PERMANENT','UNKNOWN'} else 'UNKNOWN'
                atomic_json(root / 'state.json', state)

        pending = []
        # Active failures have priority over recovery notices.
        for row in sorted(state['incidents'], key=lambda r: r['resolved_at'] is not None):
            phase = 'recovery' if row['resolved_at'] else 'failure'
            if phase == 'recovery' and (now-timestamp(row['resolved_at'])).total_seconds() > 300:
                continue
            for channel, claim in alert_claims(settings, row, phase):
                key = phase + ':' + channel
                previous = row['deliveries'].get(key)
                if previous and (previous['status'] != 'TEMPORARY' or previous.get('attempt_count', 1) >= 3
                                 or (now-timestamp(previous['attempted_at'])).total_seconds() < 60):
                    continue
                if phase == 'recovery':
                    failure = row['deliveries'].get('failure:'+channel, {})
                    target = claim.get('destination_hash') or hashlib.sha256(claim['recipient'].encode()).hexdigest()
                    if failure.get('status') not in {'ACCEPTED','UNKNOWN'} or failure.get('target_hash') != target:
                        continue
                pending.append(deliver(row, phase, channel, claim))
        if pending:
            try:
                await asyncio.wait_for(asyncio.gather(*pending), timeout=60)
            except asyncio.TimeoutError:
                pass  # Started sends remain UNKNOWN; queued sends can run next tick.
        return state


def public_snapshot(settings, tenant, *, now=None):
    if tenant != settings.auth_tenant_id:
        return dict(state='unconfigured', checked_at=None, checks=[], incidents=[], delivery_enabled=False)
    try:
        state = load_state(settings)
        checked = timestamp(state['checked_at']) if state['checked_at'] else None
        age = ((now or utcnow())-checked).total_seconds() if checked else None
        status = 'unconfigured' if age is None else 'stale' if age > 180 or age < -30 else 'running'
        checks = [result(c['key'], c['status'], c['code'], **{k:c[k] for k in ('count','last_success_at') if k in c}) for c in state['checks']]
        incidents = [dict(id=r['id'], key=r['key'], name=CHECKS[r['key']], message=MESSAGES[r['code']],
                         opened_at=r['opened_at'], last_seen_at=r['last_seen_at'], resolved_at=r['resolved_at'],
                         deliveries={k:{'status':d['status'],'attempted_at':d['attempted_at'], 'attempt_count':d.get('attempt_count',1)} for k,d in r['deliveries'].items()})
                     for r in reversed(state['incidents'])]
        return dict(state=status, checked_at=state['checked_at'], checks=checks,
                    incidents=incidents, delivery_enabled=settings.ops_alert_delivery_enabled,
                    channels=[c for c, _ in alert_claims(settings, {'key':'application','id':'0'*32}, 'failure')])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return dict(state='invalid', checked_at=None, checks=[], incidents=[], delivery_enabled=settings.ops_alert_delivery_enabled)
