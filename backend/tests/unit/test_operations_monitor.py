import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import sys

import httpx
import pytest
from app.core.config import Settings
from app.ops import operations_monitor as ops
from app.ops.operational_errors import OperationalErrorHandler
from scripts.run_monitored_backup import run_backup

NOW = datetime(2026, 10, 23, 3, tzinfo=timezone.utc)


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, ops_state_dir=str(tmp_path/'private'), auth_tenant_id='monitor-test',
                    ops_alert_delivery_enabled=False, ops_model_probes_enabled=False)


def check(status='FAIL', key='application'):
    return [ops.result(key, status, 'unavailable' if status == 'FAIL' else 'healthy' if status == 'PASS' else 'disabled')]


def enable(settings, **changes):
    return settings.model_copy(update=dict(ops_alert_delivery_enabled=True, smtp_enabled=True,
        smtp_host='smtp.example.test', smtp_from='sender@example.test', ops_alert_email_to='ops@example.test', **changes))


async def test_fault_restart_warn_recovery_and_recurrence(settings):
    first = await ops.tick(settings, now=NOW, checks=check())
    incident = first['incidents'][0]['id']
    repeated = await ops.tick(settings, now=NOW+timedelta(seconds=60), checks=check())
    assert len(repeated['incidents']) == 1
    assert repeated['incidents'][0]['id'] == incident
    warning = await ops.tick(settings, now=NOW+timedelta(seconds=120), checks=check('WARN'))
    assert warning['incidents'][0]['resolved_at'] is None
    recovered = await ops.tick(settings, now=NOW+timedelta(seconds=180), checks=check('PASS'))
    assert recovered['incidents'][0]['resolved_at'] == ops.stamp(NOW+timedelta(seconds=180))
    recurred = await ops.tick(settings, now=NOW+timedelta(seconds=240), checks=check())
    assert len(recurred['incidents']) == 2
    assert recurred['incidents'][1]['id'] != incident


async def test_delivery_once_per_phase_persisted_before_io_and_no_secret_content(settings):
    settings = enable(settings)
    seen = []
    def send(claim):
        state = ops.load_state(settings)
        assert list(state['incidents'][0]['deliveries'].values())[-1]['status'] == 'UNKNOWN'
        seen.append(claim)
        return 'ACCEPTED'
    for offset, status in [(0,'FAIL'),(60,'FAIL'),(120,'PASS'),(180,'PASS')]:
        await ops.tick(settings, now=NOW+timedelta(seconds=offset), checks=check(status), senders={'smtp':send})
    assert len(seen) == 2 and seen[0]['message_id'] != seen[1]['message_id']
    assert '恢复' in seen[1]['body'] and 'example.test' not in seen[0]['body']
    assert 'target_hash' not in json.dumps(ops.public_snapshot(settings, settings.auth_tenant_id, now=NOW))


@pytest.mark.parametrize('outcome', ['UNKNOWN','PERMANENT','unrecognized'])
async def test_ambiguous_or_terminal_results_never_retried(settings, outcome):
    settings = enable(settings)
    calls = []
    def send(claim): calls.append(claim); return outcome
    for offset in (0,60,120,180):
        await ops.tick(settings, now=NOW+timedelta(seconds=offset), checks=check(), senders={'smtp':send})
    assert len(calls) == 1


async def test_crash_after_intent_never_replays_unknown(settings):
    settings = enable(settings)
    def send(claim): raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await ops.tick(settings, now=NOW, checks=check(), senders={'smtp':send})
    assert ops.load_state(settings)['incidents'][0]['deliveries']['failure:smtp']['status'] == 'UNKNOWN'
    def forbidden(claim): pytest.fail('Ambiguous send must not replay')
    await ops.tick(settings, now=NOW+timedelta(seconds=60), checks=check(), senders={'smtp':forbidden})


async def test_known_temporary_failure_has_bounded_retries(settings):
    settings = enable(settings)
    calls = []
    def send(claim): calls.append(claim); return 'TEMPORARY'
    for offset in (0,30,60,120,180,240):
        await ops.tick(settings, now=NOW+timedelta(seconds=offset), checks=check(), senders={'smtp':send})
    assert len(calls) == 3
    assert len({c['message_id'] for c in calls}) == 1


async def test_opt_in_and_same_destination_recovery(settings):
    def forbidden(claim): pytest.fail('No transport authorized')
    await ops.tick(settings, now=NOW, checks=check(), senders={'smtp':forbidden})
    settings = enable(settings)
    # A fault which recovers before alerts are enabled produces no recovery notice.
    await ops.tick(settings, now=NOW+timedelta(seconds=60), checks=check('PASS'), senders={'smtp':forbidden})
    await ops.tick(settings, now=NOW+timedelta(seconds=120), checks=check(), senders={'smtp':lambda c:'ACCEPTED'})
    changed = settings.model_copy(update={'ops_alert_email_to':'another@example.test'})
    await ops.tick(changed, now=NOW+timedelta(seconds=180), checks=check('PASS'), senders={'smtp':forbidden})


async def test_wecom_scope_and_new_channel_cannot_receive_unrelated_recovery(settings):
    settings = settings.model_copy(update=dict(ops_alert_delivery_enabled=True, wecom_enabled=True,
        wecom_tenant_id=settings.auth_tenant_id, wecom_department_id='ops',
        wecom_webhook_url=__import__('pydantic').SecretStr('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-only')))
    seen = []
    def send(claim): seen.append(claim); return 'ACCEPTED'
    await ops.tick(settings, now=NOW, checks=check(), senders={'wecom':send})
    await ops.tick(enable(settings), now=NOW+timedelta(seconds=60), checks=check('PASS'),
                   senders={'wecom':send, 'smtp':lambda c:pytest.fail('No SMTP failure preceded recovery')})
    assert len(seen) == 2 and '恢复' in seen[-1]['body']
    mismatched = settings.model_copy(update={'wecom_tenant_id':'other'})
    assert list(ops.alert_claims(mismatched, {'key':'application','id':'0'*32}, 'failure')) == []


async def test_snapshot_is_scoped_projected_and_stale(settings):
    await ops.tick(settings, now=NOW, checks=check())
    state = ops.load_state(settings)
    state['checks'][0].update(name='secret-name',message='secret-message',private='secret-data')
    state['incidents'][0].update(name='secret-name',message='secret-message',private='secret-data')
    ops.atomic_json(Path(settings.ops_state_dir)/'state.json', state)
    public = ops.public_snapshot(settings, settings.auth_tenant_id, now=NOW)
    assert public['state'] == 'running' and 'secret' not in json.dumps(public)
    assert ops.public_snapshot(settings, 'other', now=NOW)['incidents'] == []
    assert ops.public_snapshot(settings, settings.auth_tenant_id, now=NOW+timedelta(seconds=181))['state'] == 'stale'
    assert ops.public_snapshot(settings, settings.auth_tenant_id, now=NOW-timedelta(seconds=31))['state'] == 'stale'


@pytest.mark.parametrize('data', [[],{}, {'version':2}, {'version':1,'tenant_id':'other'}, 'broken'])
def test_bad_state_fails_closed(settings, data):
    ops.atomic_json(Path(settings.ops_state_dir)/'state.json',data)
    assert ops.public_snapshot(settings, settings.auth_tenant_id, now=NOW)['state'] == 'invalid'


def test_history_is_bounded_and_lock_releases(settings):
    state = ops.new_state(settings)
    for index in range(103):
        now = NOW+timedelta(seconds=index*2)
        ops.reconcile(state,check(),now)
        ops.reconcile(state,check('PASS'),now+timedelta(seconds=1))
    ops.reconcile(state,check(),NOW+timedelta(seconds=210))
    assert len(state['incidents']) == 101
    lock = Path(settings.ops_state_dir)/'test.lock'
    with ops.exclusive(lock):
        with pytest.raises(OSError):
            with ops.exclusive(lock): pass
    with ops.exclusive(lock): pass


def backup_receipt(settings, **updates):
    data = dict(version=1,tenant_id=settings.auth_tenant_id,status='SUCCESS',started_at=ops.stamp(NOW-timedelta(minutes=1)),
                completed_at=ops.stamp(NOW),artifact_bytes=10,artifact_sha256='a'*64)
    ops.atomic_json(Path(settings.ops_state_dir)/'backup.json',dict(data,**updates))


@pytest.mark.parametrize('updates,code', [({},'healthy'),({'status':'FAILED'},'failed'),({'status':'RUNNING'},'running'),
    ({'status':'RUNNING','started_at':ops.stamp(NOW-timedelta(hours=2))},'timeout'),
    ({'artifact_bytes':0},'invalid'),({'artifact_sha256':'bad'},'invalid'),({'tenant_id':'other'},'invalid'),
    ({'started_at':ops.stamp(NOW-timedelta(days=2)),'completed_at':ops.stamp(NOW-timedelta(hours=26))},'overdue')])
def test_backup_receipt_validation(settings,updates,code):
    backup_receipt(settings,**updates)
    assert ops.backup_check(settings,NOW)['code'] == code


def test_backup_missing_and_real_command_artifact_checksum(settings,tmp_path):
    assert ops.backup_check(settings,NOW)['code'] == 'missing'
    artifact = tmp_path/'new.dump'
    command = [sys.executable,'-c',"from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'backup-data')",str(artifact)]
    assert run_backup(settings,artifact,command)
    receipt = ops.read_json(Path(settings.ops_state_dir)/'backup.json')
    assert receipt['artifact_sha256'] == hashlib.sha256(b'backup-data').hexdigest()
    assert receipt['artifact_bytes'] == 11
    assert not run_backup(settings,artifact,command)
    assert artifact.read_bytes() == b'backup-data'
    assert ops.backup_check(settings,ops.utcnow())['code'] == 'failed'


@pytest.mark.parametrize('program', ['raise SystemExit(2)', 'pass'])
def test_failed_or_absent_backup_is_never_success(settings,tmp_path,program):
    assert not run_backup(settings,tmp_path/'absent.dump',[sys.executable,'-c',program])
    assert ops.read_json(Path(settings.ops_state_dir)/'backup.json')['status'] == 'FAILED'


def test_backup_timeout_records_failure(settings,tmp_path,monkeypatch):
    import subprocess
    def timeout(*args,**kwargs): raise subprocess.TimeoutExpired('redacted',60)
    monkeypatch.setattr('scripts.run_monitored_backup.subprocess.run',timeout)
    assert not run_backup(settings,tmp_path/'timeout.dump',['trusted-backup'])
    assert ops.backup_check(settings,ops.utcnow())['code'] == 'failed'


def test_error_capture_filters_and_never_stores_messages(settings):
    handler = OperationalErrorHandler(settings)
    record = logging.LogRecord('app.services.test',logging.ERROR,'secret-path',1,'API_KEY=secret',(),None)
    handler.emit(record)
    raw = handler.path.read_text(encoding='utf-8')
    assert 'secret' not in raw and 'API_KEY' not in raw
    assert ops.critical_error_check(settings,ops.utcnow())['status'] == 'FAIL'
    assert ops.critical_error_check(settings,ops.utcnow()+timedelta(seconds=301))['status'] == 'PASS'
    handler.emit(logging.LogRecord('httpx',logging.ERROR,'',1,'private',(),None))
    assert handler.path.read_text(encoding='utf-8') == raw


async def test_collect_dependency_failure_is_safe_and_models_remain_unprobed(settings,monkeypatch):
    def database(*args): raise RuntimeError('password=secret database-address')
    monkeypatch.setattr(ops,'database_checks',database)
    client_type = httpx.AsyncClient
    def make_client(**kwargs):
        return client_type(**kwargs,transport=httpx.MockTransport(lambda r:httpx.Response(503,json={'status':'bad'})))
    monkeypatch.setattr(ops.httpx,'AsyncClient',make_client)
    checks = await ops.collect(settings,now=NOW)
    by_key = {c['key']:c for c in checks}
    assert len(by_key) == 9 and by_key['log_keywords']['code'] == 'log_disabled'
    assert by_key['application']['status'] == by_key['database']['status'] == 'FAIL'
    assert by_key['notification_backlog']['status'] == 'WARN'
    assert all(by_key[k]['code'] == 'disabled' for k in ('text_model','standby_model','embedding'))
    assert 'secret' not in json.dumps(checks)


async def test_collect_real_probe_branches_without_live_calls(settings,monkeypatch):
    from app.ops import live_services
    calls = []
    async def text(provider):
        calls.append(provider)
        if provider == 'deepseek': raise RuntimeError('private provider response')
    async def embedding(settings): calls.append('embedding')
    monkeypatch.setattr(live_services,'text_probe',text)
    monkeypatch.setattr(live_services,'embedding_probe',embedding)
    monkeypatch.setattr(ops,'database_checks',lambda *a:[ops.result('database','PASS','healthy'),ops.result('notification_backlog','PASS','healthy',count=0)])
    client_type = httpx.AsyncClient
    monkeypatch.setattr(ops.httpx,'AsyncClient',lambda **kwargs:client_type(**kwargs,transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'status':'ok'}))))
    settings = settings.model_copy(update=dict(ai_enabled=True,ops_model_probes_enabled=True,llm_provider='deepseek',llm_fallback_provider='ark',embedding_provider='ark'))
    checks = {c['key']:c for c in await ops.collect(settings,now=NOW)}
    assert checks['application']['status'] == checks['embedding']['status'] == checks['standby_model']['status'] == 'PASS'
    assert checks['text_model']['status'] == 'FAIL' and len(calls) == 3
