import json
from pydantic import SecretStr
import pytest
from app.core.config import Settings
from scripts.check_meeting_transcription_config import check_configuration, main, public_callback_url


def ready_settings():
    return Settings(_env_file=None, ai_enabled=True, trtc_sdk_app_id=12345,
        trtc_sdk_secret_key=SecretStr('private-sdk-value'),
        meeting_transcription_secret_id=SecretStr('private-cloud-id'),
        meeting_transcription_secret_key=SecretStr('private-cloud-key'),
        meeting_transcription_callback_key=SecretStr('a' * 24),
        meeting_transcription_callback_url='https://oa.company.com/api/meeting-transcriptions/callback/trtc',
        meeting_transcription_enabled=False)


def test_ready_config_does_not_enable_feature_or_print_secrets():
    report = check_configuration(ready_settings())
    assert report['ready_to_enable'] and not report['enabled'] and not report['locally_enabled']
    assert not report['network_requests'] and not report['cloud_acceptance']
    for secret in ['private-sdk-value', 'private-cloud-id', 'private-cloud-key', 'a' * 24]:
        assert secret not in json.dumps(report)


@pytest.mark.parametrize('url', [
    'http://oa.company.com/api/meeting-transcriptions/callback/trtc',
    'https://localhost/api/meeting-transcriptions/callback/trtc',
    'https://127.0.0.1/api/meeting-transcriptions/callback/trtc',
    'https://192.168.1.3/api/meeting-transcriptions/callback/trtc',
    'https://[::1]/api/meeting-transcriptions/callback/trtc',
    'https://[broken', 'https://oa.company.com:bad/api/meeting-transcriptions/callback/trtc',
    'https://oa.company.com/api/wrong',
    'https://user:password@oa.company.com/api/meeting-transcriptions/callback/trtc',
    'https://oa.example.test/api/meeting-transcriptions/callback/trtc',
])
def test_rejects_unusable_callback_urls_without_network(url):
    assert not public_callback_url(url, '/api')


def test_custom_api_prefix_and_missing_secrets():
    assert public_callback_url('https://oa.company.com/oa-api/meeting-transcriptions/callback/trtc', '/oa-api')
    settings = ready_settings().model_copy(update={'meeting_transcription_secret_key': SecretStr('')})
    report = check_configuration(settings)
    assert not report['ready_to_enable']
    assert [c['name'] for c in report['checks'] if not c['passed']] == ['MEETING_TRANSCRIPTION_SECRET_KEY']


def test_missing_file_reports_failure(tmp_path, capsys):
    assert main(['--env-file', str(tmp_path / 'missing.env')]) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'env_file_missing'


def test_invalid_settings_never_echo_raw_input(monkeypatch, capsys):
    from scripts import check_meeting_transcription_config as script
    from pydantic import ValidationError
    def invalid_settings(**kwargs):
        raise ValidationError.from_exception_data('Settings', [dict(type='int_parsing',
            loc=('trtc_sdk_app_id',), input='private-do-not-print')])
    monkeypatch.setattr(script, 'Settings', invalid_settings)
    assert main(['--env-file', __file__]) == 1
    output = capsys.readouterr().out
    assert 'private-do-not-print' not in output
    assert json.loads(output)['fields'] == [dict(name='trtc_sdk_app_id', code='int_parsing')]


@pytest.mark.parametrize('url', ['https://[broken', 'https://oa.company.com:invalid/callback'])
def test_invalid_url_disables_provider_instead_of_crashing_status(monkeypatch, url):
    from app.providers import meeting_transcription as cloud
    settings = ready_settings().model_copy(update={'meeting_transcription_enabled': True,
        'meeting_transcription_callback_url': url})
    monkeypatch.setattr(cloud.config, 'get_settings', lambda: settings)
    assert cloud.configured() is False
