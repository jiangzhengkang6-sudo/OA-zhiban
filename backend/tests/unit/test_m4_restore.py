from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.ops.m4_archive import InvalidBackupError, create_backup
from app.ops.m4_restore import restore_backup
from app.ops.m4_safety import DrillTarget, UnsafeTargetError, validate_drill_target


@pytest.fixture
def targets(tmp_path, monkeypatch):
    monkeypatch.setattr('app.ops.m4_safety.M4_DRILL_ROOT', tmp_path)
    def target(name):
        return validate_drill_target(DrillTarget(f'oa-m4-{name}', 'm4-db', f'oa_m4_{name}_test',
            f'oa-m4-{name}-pgdata', tmp_path / name, 'M4_DRILL'))
    return target('source'), target('destination')


@pytest.fixture
def backup(targets, tmp_path):
    source, _ = targets
    for component in ('attachments', 'knowledge', 'audit_exports'):
        (source.file_root / component).mkdir(parents=True)
    (source.file_root / 'knowledge/doc.txt').write_text('synthetic knowledge')
    with patch('app.ops.m4_archive.dump_database', side_effect=lambda t, p: p.write_bytes(b'PGDMP-test')):
        return create_backup(source, tmp_path / 'archive', datetime.now(timezone.utc))


@pytest.mark.parametrize('mutation', ['same', 'shared-volume', 'shared-project', 'nested-files', 'forged'])
def test_unsafe_target_never_calls_database(targets, backup, mutation):
    source, destination = targets
    if mutation == 'same':
        destination = source
    elif mutation == 'shared-volume':
        destination = replace(destination, volume_name=source.volume_name)
    elif mutation == 'shared-project':
        destination = replace(source, file_root=destination.file_root)
    elif mutation == 'nested-files':
        destination = validate_drill_target(DrillTarget(destination.compose_project, 'm4-db', destination.database_name,
            destination.volume_name, source.file_root / 'nested', 'M4_DRILL'))
    else:
        destination = replace(destination, database_name='oa_agent')
    with patch('app.ops.m4_restore.assert_database_container') as probe:
        with pytest.raises(UnsafeTargetError):
            restore_backup(backup, source, destination)
        probe.assert_not_called()


def test_tampered_archive_has_no_destination_side_effects(targets, backup):
    (backup.backup_dir / 'knowledge/doc.txt').write_text('tampered')
    with patch('app.ops.m4_restore.assert_database_container') as probe:
        with pytest.raises(InvalidBackupError):
            restore_backup(backup, *targets)
        probe.assert_not_called()
    assert not targets[1].file_root.exists()


def test_nonempty_files_are_rejected(targets, backup):
    destination = targets[1]
    destination.file_root.mkdir()
    (destination.file_root / 'existing').write_text('preserve')
    with patch('app.ops.m4_restore.assert_database_container') as probe:
        with pytest.raises(UnsafeTargetError):
            restore_backup(backup, *targets)
        probe.assert_not_called()
    assert (destination.file_root / 'existing').read_text() == 'preserve'


def test_nonempty_database_is_rejected(targets, backup):
    with patch('app.ops.m4_restore.assert_database_container'), patch('app.ops.m4_restore.database_is_empty', return_value=False):
        with pytest.raises(UnsafeTargetError):
            restore_backup(backup, *targets)
    assert not targets[1].file_root.exists()


def test_success_copies_files_only_after_database_restore(targets, backup):
    with patch('app.ops.m4_restore.assert_database_container'), patch('app.ops.m4_restore.database_is_empty', return_value=True), \
         patch('app.ops.m4_restore.restore_database') as restore:
        result = restore_backup(backup, *targets)
    restore.assert_called_once()
    assert result.success
    assert (targets[1].file_root / 'knowledge/doc.txt').read_text() == 'synthetic knowledge'
    assert not (targets[1].file_root / 'manifest.json').exists()


def test_failed_restore_does_not_copy_files(targets, backup):
    with patch('app.ops.m4_restore.assert_database_container'), patch('app.ops.m4_restore.database_is_empty', return_value=True), \
         patch('app.ops.m4_restore.restore_database', side_effect=RuntimeError('failed')):
        with pytest.raises(RuntimeError):
            restore_backup(backup, *targets)
    assert not targets[1].file_root.exists()


def test_restore_command_uses_single_transaction_without_clean(targets, backup):
    from app.ops.m4_restore import restore_database
    with patch('app.ops.m4_restore.compose_run') as run:
        restore_database(targets[1], backup.backup_dir / 'database/postgres.dump')
    args = run.call_args.args[1]
    assert '--clean' not in args
    assert '--single-transaction' in args
    assert targets[1].database_name in args
