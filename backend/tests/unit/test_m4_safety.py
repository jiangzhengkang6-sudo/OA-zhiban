import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from app.ops.m4_safety import DrillTarget, UnsafeTargetError, validate_drill_target


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _render_compose(tmp_path, *, overlay, include_password=True, scanner=False):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker Compose CLI is unavailable")

    env_file = tmp_path / "m4-synthetic.env"
    values = [
        "M4_DATABASE_NAME=oa_m4_config_test_test",
        "M4_DATABASE_URL=postgresql+asyncpg://oa:m4-synthetic-only-password@m4-db:5432/oa_m4_config_test_test",
        "M4_DATABASE_SYNC_URL=postgresql+psycopg://oa:m4-synthetic-only-password@m4-db:5432/oa_m4_config_test_test",
        "M4_CHECKPOINTER_URL=postgresql://oa:m4-synthetic-only-password@m4-db:5432/oa_m4_config_test_test",
        "FRONTEND_PORT=15173",
        "AUTH_PROVIDER=builtin",
        "AUTH_TENANT_ID=m4-synthetic",
        "AUTH_JWT_SECRET=M4-synthetic-jwt-for-config-validation-only",
        'AUTH_ALLOWED_ORIGINS=["https://oa.example.test"]',
        "AI_ENABLED=false",
        "POSTGRES_DB=oa_m4_custom_test",
        "SMTP_ENABLED=true",
        "SMTP_HOST=smtp.example.test",
        "SMTP_PORT=2525",
        "SMTP_FROM=oa@example.test",
        "SMTP_USERNAME=synthetic-user",
        "SMTP_PASSWORD=synthetic-mail-secret",
        "SMTP_STARTTLS=true",
        "SMTP_TIMEOUT_SECONDS=12",
        "NOTIFICATION_APP_URL=https://oa.example.test/oa/notifications",
        "WECOM_ENABLED=true",
        "WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=synthetic-robot",
        "WECOM_TENANT_ID=m4-synthetic",
        "WECOM_DEPARTMENT_ID=synthetic-department",
        "WECOM_TIMEOUT_SECONDS=8",
        "CLAMD_HOST=scanner",
        "CLAMD_PORT=3310",
        "ATTACHMENT_MAX_BYTES=10485760",
        "ATTACHMENT_SCAN_TIMEOUT_SECONDS=9",
        "CLAMAV_IMAGE=clamav/clamav:synthetic-config-only",
    ]
    if include_password:
        values.append("POSTGRES_PASSWORD=m4-synthetic-only-password")
    env_file.write_text("\n".join(values) + "\n", encoding="utf-8")
    command = [docker, "compose", "-p", "oa-m4-config-test", "--env-file", str(env_file), "-f", str(PROJECT_ROOT / "docker-compose.yml")]
    if overlay:
        command.extend(["-f", str(PROJECT_ROOT / "docker-compose.m4.yml")])
    if scanner:
        command.extend(["-f", str(PROJECT_ROOT / "docker-compose.scanner.yml")])
    command.extend(["config", "--format", "json"])
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env={key: value for key, value in os.environ.items() if key.upper() in {
            'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES'}},
        capture_output=True,
        text=True,
        check=False,
    )


def test_base_compose_has_no_fixed_container_names_or_weak_database_password(tmp_path):
    result = _render_compose(tmp_path, overlay=False)
    assert result.returncode == 0, result.stderr
    compose = json.loads(result.stdout)

    assert all("container_name" not in service for service in compose["services"].values())
    assert compose["services"]["db"]["environment"]["POSTGRES_PASSWORD"] == "m4-synthetic-only-password"
    missing_password = _render_compose(tmp_path, overlay=False, include_password=False)
    assert missing_password.returncode != 0


def test_compose_forwards_formal_identity_and_persists_managed_files(tmp_path):
    result = _render_compose(tmp_path, overlay=False)
    assert result.returncode == 0, result.stderr
    backend = json.loads(result.stdout)['services']['backend']
    env = backend['environment']
    assert env['AUTH_TENANT_ID'] == 'm4-synthetic'
    assert env['AUTH_JWT_SECRET'] == 'M4-synthetic-jwt-for-config-validation-only'
    assert json.loads(env['AUTH_ALLOWED_ORIGINS']) == ['https://oa.example.test']
    assert env['AUTH_COOKIE_SECURE'] == 'true'
    assert env['AI_ENABLED'] == 'false'
    assert any(v['target'] == '/app/data' and v['type'] == 'volume' for v in backend['volumes'])
    assert env['ATTACHMENT_STORAGE_DIR'].startswith('/app/data/')
    assert env['KNOWLEDGE_STORAGE_DIR'].startswith('/app/data/')


def test_base_compose_uses_one_explicit_database_name(tmp_path):
    result = _render_compose(tmp_path, overlay=False)
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)['services']
    assert services['db']['environment']['POSTGRES_DB'] == 'oa_m4_custom_test'
    assert '$POSTGRES_DB' in services['db']['healthcheck']['test'][-1]
    for name in ('DATABASE_URL', 'DATABASE_SYNC_URL', 'CHECKPOINTER_URL'):
        assert services['backend']['environment'][name].endswith('/oa_m4_custom_test')


def test_notification_and_scanner_settings_reach_container(tmp_path):
    result = _render_compose(tmp_path, overlay=False, scanner=True)
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)['services']
    env = services['backend']['environment']
    expected = dict(SMTP_ENABLED='true', SMTP_HOST='smtp.example.test', SMTP_PORT='2525',
        SMTP_FROM='oa@example.test', SMTP_USERNAME='synthetic-user', SMTP_PASSWORD='synthetic-mail-secret',
        SMTP_STARTTLS='true', SMTP_TIMEOUT_SECONDS='12',
        NOTIFICATION_APP_URL='https://oa.example.test/oa/notifications', WECOM_ENABLED='true',
        WECOM_WEBHOOK_URL='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=synthetic-robot',
        WECOM_TENANT_ID='m4-synthetic', WECOM_DEPARTMENT_ID='synthetic-department',
        WECOM_TIMEOUT_SECONDS='8', CLAMD_HOST='scanner', CLAMD_PORT='3310',
        ATTACHMENT_MAX_BYTES='10485760', ATTACHMENT_SCAN_TIMEOUT_SECONDS='9')
    assert {key: env[key] for key in expected} == expected
    scanner = services['scanner']
    assert scanner['image'] == 'clamav/clamav:synthetic-config-only'
    assert scanner['ports'][0]['host_ip'] == '127.0.0.1'
    assert scanner['ports'][0]['target'] == 3310
    assert int(scanner['mem_limit']) == 3 * 1024**3
    assert all(mount['target'] != '/app/data' for mount in scanner['volumes'])


def test_standalone_scanner_does_not_create_oa_services_or_business_volumes(tmp_path):
    docker = shutil.which('docker')
    if not docker:
        pytest.skip('Docker Compose CLI is unavailable')
    command = [docker, 'compose', '-p', 'oa-scanner-config-test', '-f',
               str(PROJECT_ROOT / 'docker-compose.scanner.yml'), 'config', '--format', 'json']
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES'}}
    env['CLAMAV_IMAGE'] = 'clamav/clamav:synthetic-config-only'
    # An explicit empty env file also prevents loading private project .env values.
    env_file = tmp_path / 'scanner-empty.env'
    env_file.write_text('', encoding='utf-8')
    command[2:2] = ['--env-file', str(env_file)]
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    assert set(rendered['services']) == {'scanner'}
    assert set(rendered['volumes']) == {'signatures'}


def test_m4_compose_config_isolated_and_does_not_publish_database_port(tmp_path):
    result = _render_compose(tmp_path, overlay=True)

    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    assert not rendered["services"]["db"].get("ports")
    assert all("container_name" not in service for service in rendered["services"].values())
    assert rendered["volumes"]["oa_pgdata"]["name"] == "oa-m4-config-test-pgdata"
    backend_env = rendered["services"]["backend"]["environment"]
    assert backend_env["ENVIRONMENT"] == "test"
    assert backend_env["OA_PROVIDER"] == backend_env["AUTH_PROVIDER"] == "mock"
    assert backend_env["LLM_PROVIDER"] == backend_env["EMBEDDING_PROVIDER"] == "mock"
    assert backend_env["LLM_FALLBACK_PROVIDER"] == "none"
    assert backend_env["SMTP_ENABLED"] == backend_env["WECOM_ENABLED"] == "false"
    assert backend_env["OA_API_KEY"] == backend_env["ARK_API_KEY"] == ""
    assert backend_env["DEEPSEEK_API_KEY"] == backend_env["EMBEDDING_API_KEY"] == ""
    assert backend_env['CLAMD_HOST'] == ''
    assert backend_env['SMTP_HOST'] == backend_env['SMTP_USERNAME'] == backend_env['SMTP_PASSWORD'] == ''
    assert backend_env['WECOM_WEBHOOK_URL'] == ''


@pytest.fixture
def drill_root(tmp_path, monkeypatch):
    root = tmp_path / "m4-drills"
    monkeypatch.setattr("app.ops.m4_safety.M4_DRILL_ROOT", root)
    return root


def make_target(root, **overrides):
    values = {
        "compose_project": "oa-m4-run-001",
        "database_host": "m4-db",
        "database_name": "oa_m4_run_001_test",
        "volume_name": "oa-m4-run-001-pgdata",
        "file_root": root / "oa-m4-run-001",
        "drill_marker": "M4_DRILL",
    }
    values.update(overrides)
    return DrillTarget(**values)


def test_rejects_target_without_explicit_drill_marker(drill_root):
    target = make_target(drill_root, drill_marker="")
    with pytest.raises(UnsafeTargetError):
        validate_drill_target(target)


def test_rejects_database_outside_m4_test_allowlist(drill_root):
    target = make_target(drill_root, database_name="oa_agent")
    with pytest.raises(UnsafeTargetError):
        validate_drill_target(target)


def test_rejects_target_matching_source_identity(drill_root):
    root = (drill_root / "oa-m4-run-001").as_posix().casefold()
    source_identity = "/".join(("oa-m4-run-001", "m4-db", "oa_m4_run_001_test", "oa-m4-run-001-pgdata", root))
    target = make_target(drill_root, source_identity=source_identity)
    with pytest.raises(UnsafeTargetError):
        validate_drill_target(target)


def test_rejects_unapproved_compose_project(drill_root):
    target = make_target(drill_root, compose_project="oa-agent-preview")
    with pytest.raises(UnsafeTargetError):
        validate_drill_target(target)


def test_rejects_volume_owned_by_another_project(drill_root):
    target = make_target(drill_root, volume_owner_project="oa-agent-preview")
    with pytest.raises(UnsafeTargetError):
        validate_drill_target(target)


def test_rejects_file_root_outside_allowlist(drill_root, tmp_path):
    target = make_target(drill_root, file_root=tmp_path / "preview-data")
    with pytest.raises(UnsafeTargetError):
        validate_drill_target(target)


def test_error_does_not_disclose_database_credentials(drill_root):
    target = make_target(drill_root, database_host="postgresql://admin:secret@preview-db/oa_agent")
    with pytest.raises(UnsafeTargetError) as error:
        validate_drill_target(target)
    assert "secret" not in str(error.value)
