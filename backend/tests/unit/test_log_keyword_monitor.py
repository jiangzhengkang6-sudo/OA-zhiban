from datetime import timedelta
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.ops import operations_monitor as ops
from app.ops.log_keywords import scan, READ_LIMIT
from tests.unit.test_operations_monitor import NOW


def configured(tmp_path, *files, keywords=None):
    return Settings(_env_file=None, auth_tenant_id='log-test', ops_state_dir=str(tmp_path/'state'),
                    ops_log_files=[str(p) for p in files],
                    ops_log_keywords=keywords or ['ERROR', '严重故障'])


def test_unconfigured_is_warning_and_does_not_create_receipt(tmp_path):
    settings = configured(tmp_path)
    assert scan(settings, NOW)['code'] == 'log_disabled'
    assert not (tmp_path/'state/logs.json').exists()


def test_incremental_scan_restart_and_recovery_never_store_content(tmp_path):
    logfile = tmp_path/'private-service.log'
    logfile.write_text('normal\nerror API_KEY=secret-value\n', encoding='utf-8')
    settings = configured(tmp_path, logfile)
    assert scan(settings, NOW)['status'] == 'FAIL'
    assert scan(settings, NOW+timedelta(seconds=299))['status'] == 'FAIL'
    assert scan(settings, NOW+timedelta(seconds=301))['status'] == 'PASS'
    receipt = (tmp_path/'state/logs.json').read_text(encoding='utf-8')
    assert all(secret not in receipt for secret in ('secret-value','API_KEY','private-service.log','error'))
    with logfile.open('a',encoding='utf-8') as stream:
        stream.write('严重故障：内部材料\n')
    assert scan(settings, NOW+timedelta(seconds=302))['status'] == 'FAIL'
    assert '内部材料' not in (tmp_path/'state/logs.json').read_text(encoding='utf-8')


@pytest.mark.parametrize('keyword', ['ERROR', '严重故障'])
def test_match_crossing_read_or_append_boundary(tmp_path, keyword):
    logfile = tmp_path/'service.log'
    raw = keyword.encode('utf-8')
    logfile.write_bytes(b'x'*(READ_LIMIT-2)+raw)
    settings = configured(tmp_path, logfile, keywords=[keyword])
    assert scan(settings,NOW)['code'] == 'log_catching_up'
    assert scan(settings,NOW+timedelta(seconds=60))['code'] == 'log_matched'
    assert scan(settings,NOW+timedelta(seconds=361))['status'] == 'PASS'
    with logfile.open('ab') as stream: stream.write(raw[:2])
    assert scan(settings,NOW+timedelta(seconds=362))['status'] == 'PASS'
    with logfile.open('ab') as stream: stream.write(raw[2:])
    assert scan(settings,NOW+timedelta(seconds=363))['status'] == 'FAIL'


def test_rotation_and_copy_truncate_regrowth_are_detected(tmp_path):
    logfile = tmp_path/'service.log'
    logfile.write_bytes(b'x'*300)
    settings = configured(tmp_path, logfile)
    assert scan(settings,NOW)['status'] == 'PASS'
    logfile.rename(tmp_path/'service.log.1')
    logfile.write_bytes(b'ERROR rotated\n')
    assert scan(settings,NOW+timedelta(seconds=60))['status'] == 'FAIL'
    assert scan(settings,NOW+timedelta(seconds=361))['status'] == 'PASS'
    logfile.write_bytes(b'ERROR replaced and regrown\n'+b'y'*400)
    assert scan(settings,NOW+timedelta(seconds=362))['status'] == 'FAIL'
    logfile.write_bytes(b'fine\n')
    assert scan(settings,NOW+timedelta(seconds=663))['status'] == 'PASS'


def test_missing_unreadable_directory_and_cursor_corruption_fail_closed(tmp_path):
    logfile = tmp_path/'service.log'
    settings = configured(tmp_path, logfile)
    assert scan(settings,NOW)['code'] == 'log_unreadable'
    logfile.mkdir()
    assert scan(settings,NOW)['code'] == 'log_unreadable'
    logfile.rmdir(); logfile.write_bytes(b'fine')
    assert scan(settings,NOW)['status'] == 'PASS'
    receipt = tmp_path/'state/logs.json'
    data = json.loads(receipt.read_text(encoding='utf-8'))
    data['sources'][next(iter(data['sources']))]['offset'] = -1
    ops.atomic_json(receipt, data)
    assert scan(settings,NOW)['code'] == 'log_invalid'
    assert json.loads(receipt.read_text())['sources'] == data['sources']


def test_permission_failure_does_not_leak_error_or_mask_other_file_match(tmp_path, monkeypatch):
    import app.ops.log_keywords as logs
    good, denied = tmp_path/'good.log', tmp_path/'denied.log'
    good.write_bytes(b'ERROR private'); denied.write_bytes(b'fine')
    settings = configured(tmp_path,good,denied)
    original = logs.os.open
    def open_file(path, *args, **kwargs):
        if Path(path) == denied: raise PermissionError('password=secret')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(logs.os,'open',open_file)
    result = scan(settings,NOW)
    assert result['status'] == 'FAIL' and result['code'] == 'log_unreadable'
    assert 'secret' not in json.dumps(result)
    monkeypatch.setattr(logs.os,'open',original)
    assert scan(settings,NOW+timedelta(seconds=60))['code'] == 'log_matched'


@pytest.mark.parametrize('field,value', [('ops_log_files',['relative.log']), ('ops_log_files',['/tmp/a']*9),
    ('ops_log_keywords',[]), ('ops_log_keywords',['']), ('ops_log_keywords',['x'*129]),
    ('ops_log_keywords',['x']*17)])
def test_configuration_limits(tmp_path, field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field:value})


def test_configuration_changes_rescan_and_private_state_cannot_be_log_source(tmp_path):
    logfile = tmp_path/'service.log'
    logfile.write_bytes(b'CUSTOM private')
    settings = configured(tmp_path,logfile)
    assert scan(settings,NOW)['status'] == 'PASS'
    changed = configured(tmp_path,logfile,keywords=['CUSTOM'])
    assert scan(changed,NOW+timedelta(seconds=1))['status'] == 'FAIL'
    forbidden = configured(tmp_path,tmp_path/'state/logs.json')
    assert scan(forbidden,NOW)['code'] == 'log_unreadable'


async def test_keyword_fault_uses_existing_dedup_and_recovery_without_live_sends(tmp_path):
    logfile = tmp_path/'service.log'
    logfile.write_bytes(b'ERROR sensitive detail')
    settings = configured(tmp_path,logfile).model_copy(update=dict(ops_alert_delivery_enabled=True,
        smtp_enabled=True,smtp_host='test.invalid',smtp_from='from@test.invalid',ops_alert_email_to='ops@test.invalid'))
    sent = []
    def send(claim): sent.append(claim); return 'ACCEPTED'
    for offset in (0,60,301,360):
        now = NOW+timedelta(seconds=offset)
        await ops.tick(settings,now=now,checks=[scan(settings,now)],senders={'smtp':send})
    assert len(sent) == 2 and '恢复' in sent[1]['body']
    assert all('sensitive' not in claim['body'] for claim in sent)
    public = ops.public_snapshot(settings,settings.auth_tenant_id,now=NOW+timedelta(seconds=360))
    assert len(public['incidents']) == 1 and public['incidents'][0]['resolved_at']
    assert str(logfile) not in json.dumps(public)


@pytest.mark.parametrize('mutation', ['tenant', 'future', 'shape', 'oversize'])
def test_invalid_receipts_are_preserved_even_when_configuration_changes(tmp_path, mutation):
    logfile = tmp_path/'service.log'
    logfile.write_bytes(b'fine')
    settings = configured(tmp_path, logfile)
    scan(settings,NOW)
    receipt = tmp_path/'state/logs.json'
    data = json.loads(receipt.read_text(encoding='utf-8'))
    if mutation == 'tenant': data['tenant_id'] = 'another-tenant'
    if mutation == 'future': next(iter(data['sources'].values()))['last_match_at'] = ops.stamp(NOW+timedelta(days=1))
    if mutation == 'shape': data['sources'] = []
    if mutation == 'oversize': data['unexpected'] = 'x'*(2*1024*1024)
    ops.atomic_json(receipt,data)
    before = receipt.read_bytes()
    assert scan(configured(tmp_path,logfile,keywords=['CUSTOM']),NOW)['code'] == 'log_invalid'
    assert receipt.read_bytes() == before


def test_short_keyword_in_lookbehind_is_not_reported_again(tmp_path):
    logfile = tmp_path/'service.log'
    logfile.write_bytes(b'ERROR previous')
    settings = configured(tmp_path,logfile,keywords=['ERROR','a much longer keyword'])
    assert scan(settings,NOW)['status'] == 'FAIL'
    with logfile.open('ab') as stream: stream.write(b' normal')
    assert scan(settings,NOW+timedelta(seconds=301))['status'] == 'PASS'


def test_failed_persistence_does_not_report_healthy(tmp_path,monkeypatch):
    logfile = tmp_path/'service.log'
    logfile.write_bytes(b'fine')
    def failed(*args): raise OSError('private storage path')
    monkeypatch.setattr('app.ops.log_keywords.atomic_json',failed)
    checked = scan(configured(tmp_path,logfile),NOW)
    assert checked['status'] == 'FAIL' and checked['code'] == 'log_unreadable'
    assert 'private storage' not in json.dumps(checked)
