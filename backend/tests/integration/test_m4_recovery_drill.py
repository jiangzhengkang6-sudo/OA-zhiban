"""Opt-in host orchestrator. All application code runs in isolated Docker networks."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
import inspect
import os
from pathlib import Path
import shutil
import subprocess
import re
import tarfile
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.ops import m4_safety
from app.ops.m4_archive import create_backup, verify_backup
from app.ops.m4_metrics import calculate_recovery_metrics
from app.ops.m4_restore import restore_backup
from app.ops.m4_safety import DrillTarget, assert_database_container, compose_run, contained_path, validate_drill_target


async def seed_business():
    """Called in the synthetic container after migrations; never imports preview fixtures."""
    from unittest.mock import AsyncMock, patch
    from sqlalchemy import select
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.checkpoint.base import empty_checkpoint
    from app.core.config import get_settings
    from app.db.session import async_session_factory, engine
    from app.models.identity import OAUser
    from app.models.knowledge_source import KnowledgeSource
    from app.models.knowledge_version import KnowledgeVersion
    from app.schemas.oa_leave import LeaveDraftCreate, SubmitLeaveCommand, BalanceAdjustment
    from app.schemas.oa_workflow import DecideNodeCommand
    from app.services import oa_leave_service as leaves, oa_approval_service as approvals
    from app.services import oa_attachment_service as attachments, oa_balance_service as balances
    from app.services.credential_service import hash_password
    from tests.api.test_oa_leave_lifecycle import setup_leave, fields
    from tests.api.test_oa_leave_attachments import image_upload
    from app.db.safety import validate_test_targets

    settings = get_settings()
    validate_test_targets(settings.environment, settings.allow_test_database_reset,
                          settings.database_url, settings.database_sync_url, settings.checkpointer_url)
    with patch('app.providers.file_scanner.scan_bytes', new=AsyncMock(return_value='CLEAN')):
        async with async_session_factory() as db:
            admin, actor, workflow = await setup_leave(db)
            user = await db.get(OAUser, actor.user_id)
            user.normalized_username = 'm4-applicant'
            user.password_hash = hash_password('M4-Synthetic-Login-4719')
            await balances.adjust(db, admin, BalanceAdjustment(operation_id='quota', expected_revision=0,
                user_id=actor.user_id, leave_type='annual', year=2026, total=10, reason='synthetic M4'))
            await db.commit()
            identifiers = []
            for index, name in enumerate(('completed', 'pending')):
                drafted = await leaves.create_draft(db, actor, LeaveDraftCreate(operation_id='draft-'+name,
                    workflow_definition_id=workflow, fields=fields(f'2026-10-{20+index}', f'2026-10-{20+index}')))
                await db.commit()
                leave_id = drafted.result['id']
                uploaded = await attachments.upload(db, actor, leave_id, image_upload(), operation_id='file-'+name, expected_revision=1)
                await db.commit()
                submitted = await leaves.submit(db, actor, leave_id, SubmitLeaveCommand(operation_id='submit-'+name,
                    expected_revision=2, requested_submission_version=1))
                await db.commit()
                node = next(n for n in await approvals.list_items(db, admin, 'pending') if n['leave_id']==leave_id)
                command = DecideNodeCommand(operation_id='decision-'+name, expected_revision=node['revision'], action='approve')
                if name == 'completed':
                    await approvals.decide(db, admin, node['node_id'], command)
                    await db.commit()
                identifiers.append({'name': name, 'id': leave_id, 'node_id': node['node_id'],
                    'attachment_id': uploaded.result['attachment']['id'], 'command': command.model_dump(mode='json')})
            result = {'tenant': actor.tenant_id, 'actor': actor.user_id, 'admin': admin.user_id, 'leaves': identifiers}
            knowledge = KnowledgeSource(tenant_id=actor.tenant_id, name='M4 policy', owner_id=actor.user_id)
            db.add(knowledge)
            await db.flush()
            db.add(KnowledgeVersion(source_id=knowledge.id, version=1, status='published',
                parse_status='READY', permission_tags=['employee']))
            result['knowledge_id'] = str(knowledge.id)
            await db.commit()
    with PostgresSaver.from_conn_string(settings.checkpointer_url) as saver:
        saver.setup()
        checkpoint = empty_checkpoint()
        checkpoint['channel_values'] = {'m4_pending_leave': identifiers[1]['id']}
        saver.put({'configurable': {'thread_id': 'm4-recovery', 'checkpoint_ns': ''}}, checkpoint,
                  {'source': 'input', 'step': -1, 'parents': {}}, {})
    (Path('/m4/knowledge') / 'policy.txt').write_text('M4 synthetic leave policy', encoding='utf-8')
    (Path('/m4/audit_exports') / 'drill.json').write_text('{"synthetic":true}', encoding='utf-8')
    result['last_verified_commit_at'] = datetime.now(timezone.utc).isoformat()
    await engine.dispose()
    print(json.dumps(result))


async def verify_business(seed):
    from unittest.mock import AsyncMock, patch
    from sqlalchemy import select, func
    from langgraph.checkpoint.postgres import PostgresSaver
    from app.core.config import get_settings
    from app.db.session import async_session_factory, engine
    from app.models.identity import OAUser
    from app.models.knowledge_source import KnowledgeSource
    from app.models.knowledge_version import KnowledgeVersion
    from uuid import UUID
    from app.models.oa_leave import OALeaveBalance, OALeaveLedger
    from app.models.oa_workflow import OAWorkflowEvent, OAWorkflowOutbox, OAWorkflowOperation
    from app.services.identity_service import current_identity
    from app.services import oa_leave_service as leaves, oa_approval_service as approvals, oa_attachment_service as attachments
    from app.schemas.oa_workflow import DecideNodeCommand
    from app.services.credential_service import verify_password
    from app.db.migrations import assert_schema_current
    get_settings().auth_tenant_id = seed['tenant']
    get_settings().auth_allowed_origins = ['https://localhost']
    from app import main
    import httpx

    async with engine.connect() as connection:
        await connection.run_sync(assert_schema_current)
    async with async_session_factory() as db:
        user = await db.get(OAUser, seed['actor'])
        assert verify_password('M4-Synthetic-Login-4719', user.password_hash)
        actor = await current_identity(db, user)
        admin = await current_identity(db, await db.get(OAUser, seed['admin']))
        history = await leaves.list_leaves(db, actor)
        assert len(history) == 2
        knowledge = await db.get(KnowledgeSource, UUID(seed['knowledge_id']))
        assert knowledge.tenant_id == seed['tenant'] and knowledge.name == 'M4 policy'
        version = await db.scalar(select(KnowledgeVersion).where(KnowledgeVersion.source_id==knowledge.id))
        assert version.status == 'published' and version.parse_status == 'READY'
        async def snapshot():
            counts = []
            for model in (OALeaveLedger, OAWorkflowEvent, OAWorkflowOutbox, OAWorkflowOperation):
                counts.append(await db.scalar(select(func.count()).select_from(model).where(model.tenant_id==seed['tenant'])))
            balance = await db.scalar(select(OALeaveBalance).where(OALeaveBalance.user_id==actor.user_id))
            return counts, (balance.used, balance.reserved)
        completed, pending = seed['leaves']
        assert (await leaves.detail(db, actor, completed['id']))['state'] == 'APPROVED'
        before = await snapshot()
        replay = await approvals.decide(db, admin, completed['node_id'], DecideNodeCommand(**completed['command']))
        await db.commit()
        assert replay.replayed
        assert await snapshot() == before
        for item in seed['leaves']:
            _, content = await attachments.download(db, actor, item['id'], item['attachment_id'])
            assert content.startswith(b'\x89PNG')
        assert (await leaves.detail(db, actor, pending['id']))['state'] == 'IN_REVIEW'
        await approvals.decide(db, admin, pending['node_id'], DecideNodeCommand(**pending['command']))
        await db.commit()
        assert (await leaves.detail(db, actor, pending['id']))['state'] == 'APPROVED'
    with PostgresSaver.from_conn_string(get_settings().checkpointer_url) as saver:
        restored = saver.get_tuple({'configurable': {'thread_id': 'm4-recovery', 'checkpoint_ns': ''}})
        assert restored.checkpoint['channel_values']['m4_pending_leave'] == pending['id']
    assert Path('/m4/knowledge/policy.txt').read_text() == 'M4 synthetic leave policy'
    assert json.loads(Path('/m4/audit_exports/drill.json').read_text()) == {'synthetic': True}
    # A restored user must also pass the real login endpoint.
    with patch.object(main.runtime, 'initialize', new=AsyncMock()), patch.object(main.runtime, 'close', new=AsyncMock()):
        async with main.lifespan(main.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://localhost') as client:
                assert (await client.get('/healthz')).status_code == 200
                assert (await client.get('/api/readiness')).status_code == 200
                csrf = (await client.get('/api/auth/csrf')).json()['data']['token']
                response = await client.post('/api/auth/login', json={'username': 'm4-applicant', 'password': 'M4-Synthetic-Login-4719'},
                    headers={'origin': 'https://localhost', 'x-csrf-token': csrf})
                assert response.status_code == 200, response.text
    await engine.dispose()
    print(json.dumps({'business_verified': True, 'checks': ['login', 'history', 'attachments', 'pending_approval',
        'checkpoint', 'knowledge', 'audit_exports', 'idempotent_replay', 'readiness']}))


def run_application(target, script, *, timeout=180, application_root=None):
    tests = Path(__file__).resolve().parents[1]
    args = ['run', '--rm', '--no-deps', '--pull', 'never', '-v', f'{tests.as_posix()}:/app/tests:ro',
        '-v', f'{target.file_root.as_posix()}:/m4', '-e', 'AUTH_PROVIDER=builtin', '-e', 'OA_PROVIDER=builtin',
        '-e', 'AUTH_JWT_SECRET=M4-Synthetic-JWT-Signing-Key-Only-4719',
        '-e', 'ALLOW_TEST_DATABASE_RESET=true', '-e', 'AI_ENABLED=false',
        '-e', 'ATTACHMENT_STORAGE_DIR=/m4/attachments', '-e', 'KNOWLEDGE_STORAGE_DIR=/m4/knowledge',
        '-e', 'AUDIT_EXPORT_STORAGE_DIR=/m4/audit_exports']
    if application_root is not None:
        args += ['-v', f'{contained_path(application_root).as_posix()}:/app/app:ro']
    args += ['backend', 'python', '-c', script]
    run = subprocess.run
    def diagnostic_run(*args, **kwargs):
        result = run(*args, **kwargs)
        if result.returncode:
            output = ((result.stdout or b'') + (result.stderr or b'')).decode(errors='replace')
            output = re.sub(r'M4-Synthetic-[A-Za-z0-9-]+', '[synthetic-redacted]', output)
            output = re.sub(r'postgresql[^\s]+', '[database-url-redacted]', output)
            pytest.fail('Isolated application failed:\n' + output[-12000:])
        return result
    with patch.object(m4_safety.subprocess, 'run', side_effect=diagnostic_run):
        return compose_run(target, args, stdout=subprocess.PIPE, timeout=timeout).stdout.decode()


async def verify_rollback(seed):
    from app import main
    from app.db.session import async_session_factory, engine
    from app.models.identity import OAUser
    from app.models.oa_leave import OALeave
    from app.services.identity_service import current_identity
    from app.services import oa_leave_service as leaves, oa_approval_service as approvals
    from app.schemas.oa_leave import LeaveDraftCreate, SubmitLeaveCommand
    from app.schemas.oa_workflow import DecideNodeCommand
    from tests.api.test_oa_leave_lifecycle import fields
    import httpx

    async with main.lifespan(main.app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://localhost') as client:
            assert (await client.get('/healthz')).status_code == 200
            assert (await client.get('/api/readiness')).json()['ready']
        async with async_session_factory() as db:
            actor = await current_identity(db, await db.get(OAUser, seed['actor']))
            admin = await current_identity(db, await db.get(OAUser, seed['admin']))
            assert len(await leaves.list_leaves(db, actor)) == 2
            old = await db.get(OALeave, seed['leaves'][0]['id'])
            drafted = await leaves.create_draft(db, actor, LeaveDraftCreate(operation_id='rollback-create',
                workflow_definition_id=old.workflow_definition_id, fields=fields('2026-12-01', '2026-12-01')))
            await db.commit()
            leave_id = drafted.result['id']
            await leaves.submit(db, actor, leave_id, SubmitLeaveCommand(operation_id='rollback-submit',
                expected_revision=1, requested_submission_version=1))
            await db.commit()
            node = next(n for n in await approvals.list_items(db, admin, 'pending') if n['leave_id']==leave_id)
            command = DecideNodeCommand(operation_id='rollback-approve', expected_revision=node['revision'], action='approve')
            await approvals.decide(db, admin, node['node_id'], command)
            await db.commit()
            assert (await leaves.detail(db, actor, leave_id))['state'] == 'APPROVED'
            assert (await approvals.decide(db, admin, node['node_id'], command)).replayed
            await db.commit()
    await engine.dispose()
    print(json.dumps({'compatible_baseline': True, 'read_write_approval_replay': True}))


def verify_baseline_rollback(target, seed, evidence_root):
    from app.db.migrations import assert_application_rollback_compatible
    revision = '8cb8fc625d3bb1c175f17cb0321e32837171a6b2'
    heads = compose_run(target, ['exec', '-T', 'db', 'psql', '-U', 'oa', '-d', target.database_name,
        '-X', '-Atc', 'SELECT version_num FROM alembic_version'], stdout=subprocess.PIPE).stdout.decode().split()
    assert_application_rollback_compatible(revision, set(heads))
    archive = evidence_root / 'baseline.tar'
    subprocess.run(['git', 'archive', '--format=tar', '-o', str(archive), revision, 'backend/app'], check=True)
    exported = evidence_root / 'baseline'
    with tarfile.open(archive) as stream:
        stream.extractall(exported, filter='data')
    # Old application code cannot import the new backup/restore orchestrator.
    script = ('import asyncio,json\n' + inspect.getsource(verify_rollback) +
              f'\nasyncio.run(verify_rollback(json.loads({json.dumps(json.dumps(seed))})))')
    output = run_application(target, script, application_root=exported / 'backend/app')
    return json.loads(output.strip().splitlines()[-1])


@pytest.mark.skipif(os.environ.get('M4_RUN_DOCKER') != '1', reason='Set M4_RUN_DOCKER=1 for isolated local drill')
def test_m4_real_database_and_business_recovery():
    token = uuid4().hex[:12]
    targets = []
    for suffix in ('source', 'destination'):
        project = f'oa-m4-{token}-{suffix}'
        target = validate_drill_target(DrillTarget(project, 'm4-db', f'oa_m4_{token}_{suffix}_test',
            project+'-pgdata', m4_safety.M4_DRILL_ROOT / project, 'M4_DRILL'))
        # Unique identifiers must be absent before provisioning or cleanup is authorized.
        assert subprocess.run(['docker', 'volume', 'inspect', target.volume_name], capture_output=True).returncode != 0
        assert not target.file_root.exists()
        targets.append(target)
    source, destination = targets
    created = []
    evidence_root = contained_path(m4_safety.M4_DRILL_ROOT / ('evidence-'+token))
    evidence_root.mkdir(parents=True)
    try:
        for target in targets:
            compose_run(target, ['up', '-d', '--wait', 'db'], stdout=subprocess.PIPE)
            created.append(target)
            assert_database_container(target)
        for name in ('attachments', 'knowledge', 'audit_exports'):
            (source.file_root / name).mkdir(parents=True)
        compose_run(source, ['build', 'backend'], stdout=subprocess.PIPE, timeout=600)
        run_application(source, 'from alembic import command; from app.db.migrations import migration_config; command.upgrade(migration_config(),"head")')
        seed_output = run_application(source, 'import asyncio; from tests.integration.test_m4_recovery_drill import seed_business; asyncio.run(seed_business())')
        seed = json.loads(seed_output.strip().splitlines()[-1])
        captured = datetime.now(timezone.utc)
        backup = create_backup(source, evidence_root / 'backup', captured)
        failure = datetime.now(timezone.utc)
        started = datetime.now(timezone.utc)
        result = restore_backup(verify_backup(backup.backup_dir), source, destination)
        assert result.success
        script = ('import asyncio,json; from tests.integration.test_m4_recovery_drill import verify_business; '
                  f'asyncio.run(verify_business(json.loads({json.dumps(json.dumps(seed))})))')
        verified_output = run_application(destination, script)
        verified = datetime.now(timezone.utc)
        business = json.loads(verified_output.strip().splitlines()[-1])
        assert business['business_verified']
        metrics = calculate_recovery_metrics(failure, datetime.fromisoformat(seed['last_verified_commit_at']), started, verified)
        assert metrics.rpo_met and metrics.rto_met
        rollback = verify_baseline_rollback(destination, seed, evidence_root)
        suite = ['tests/recovery/test_m4_degradation.py', 'tests/security/test_m4_boundaries.py',
            'tests/migrations/test_m4_upgrade_rollback.py', 'tests/unit/test_wecom.py', 'tests/unit/test_oa_smtp.py',
            'tests/api/test_oa_notification.py', 'tests/api/test_oa_wecom.py',
            'tests/security/test_oa_workflow_access.py',
            'tests/integration/test_m3_audit_authority.py::test_formal_admin_role_cannot_expand_self_audit_scope',
            'tests/integration/test_m3_audit_authority.py::test_formal_department_audit_scope_requires_explicit_permission',
            'tests/integration/test_m3_audit_authority.py::test_formal_audit_permission_revocation_denies_cached_actor',
            'tests/integration/test_m3_audit_authority.py::test_formal_audit_department_move_uses_current_membership',
            'tests/integration/test_m3_audit_authority.py::test_formal_export_filters_and_serializes_datetime']
        suite_output = run_application(destination, 'import pytest; raise SystemExit(pytest.main('+repr(['-q', *suite])+'))', timeout=240)
        (evidence_root / 'suite.txt').write_text(suite_output, encoding='utf-8')
        evidence = {'source': source.identity, 'destination': destination.identity,
            'backup_id': backup.backup_id, 'captured_at': captured.isoformat(),
            'failure_at': failure.isoformat(), 'last_verified_commit_at': seed['last_verified_commit_at'],
            'recovery_started_at': started.isoformat(), 'service_verified_at': verified.isoformat(),
            'metrics': asdict(metrics), 'business': business, 'rollback': rollback,
            'archive_bytes': sum(e.size for e in backup.entries), 'file_entries': len(backup.entries),
            'limits': 'synthetic local single-run; no offsite or recurring backup evidence'}
        (evidence_root / 'recovery.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print('M4 evidence:', evidence_root)
    finally:
        for target in reversed(created):
            assert_database_container(target)
            compose_run(target, ['down', '--volumes'], stdout=subprocess.PIPE)
        for target in targets:
            if target.file_root.exists():
                contained_path(target.file_root)
                shutil.rmtree(target.file_root)
