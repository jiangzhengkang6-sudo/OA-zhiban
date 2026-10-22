import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.ops.m4_safety import DrillTarget, validate_drill_target
from app.ops.m4_archive import InvalidBackupError, create_backup, verify_backup


@pytest.fixture
def archive_target(tmp_path, monkeypatch):
    monkeypatch.setattr('app.ops.m4_safety.M4_DRILL_ROOT', tmp_path)
    target = validate_drill_target(DrillTarget('oa-m4-archive', 'm4-db', 'oa_m4_archive_test',
        'oa-m4-archive-pgdata', tmp_path / 'source', 'M4_DRILL'))
    for component in ('attachments', 'knowledge', 'audit_exports'):
        (target.file_root / component).mkdir(parents=True)
    (target.file_root / 'attachments' / 'example.txt').write_text('synthetic attachment')
    return target


@pytest.fixture
def backup(archive_target, tmp_path):
    with patch('app.ops.m4_archive.dump_database', side_effect=lambda target, path: path.write_bytes(b'PGDMP-synthetic')):
        return create_backup(archive_target, tmp_path / 'archive', datetime.now(timezone.utc))


def test_backup_roundtrip_covers_required_components(backup):
    checked = verify_backup(backup.backup_dir)
    assert checked.backup_id == backup.backup_id
    assert {entry.component for entry in checked.entries} == {'database', 'attachments', 'knowledge', 'audit_exports', 'config'}


@pytest.mark.parametrize('mutation', ['missing-field', 'absolute', 'traversal', 'windows', 'duplicate', 'missing-component'])
def test_manifest_rejects_invalid_structure(backup, mutation):
    path = backup.backup_dir / 'manifest.json'
    data = json.loads(path.read_text())
    if mutation == 'missing-field':
        del data['source_identity']
    elif mutation == 'duplicate':
        data['entries'].append(data['entries'][0])
    elif mutation == 'missing-component':
        data['entries'] = [e for e in data['entries'] if e['component'] != 'knowledge']
    else:
        data['entries'][0]['relative_path'] = {'absolute': '/outside', 'traversal': '../outside', 'windows': 'C:\\outside'}[mutation]
    path.write_text(json.dumps(data))
    with pytest.raises(InvalidBackupError):
        verify_backup(backup.backup_dir)


@pytest.mark.parametrize('mutation', ['missing', 'tampered', 'unlisted'])
def test_integrity_rejects_modified_or_unlisted_files(backup, mutation):
    path = backup.backup_dir / 'attachments/example.txt'
    if mutation == 'missing':
        path.unlink()
    elif mutation == 'tampered':
        path.write_text('modified')
    else:
        (backup.backup_dir / '.env').write_text('synthetic-only')
    with pytest.raises(InvalidBackupError):
        verify_backup(backup.backup_dir)


def test_failed_dump_never_leaves_success_manifest(archive_target, tmp_path):
    with patch('app.ops.m4_archive.dump_database', side_effect=RuntimeError('dump failed')):
        with pytest.raises(RuntimeError):
            create_backup(archive_target, tmp_path / 'failed', datetime.now(timezone.utc))
    assert not (tmp_path / 'failed').exists()


def test_backup_excludes_credentials_and_caches(archive_target, backup):
    # Files inside managed trees are screened, not blindly copied.
    (archive_target.file_root / 'attachments' / '.env').write_text('private')
    with patch('app.ops.m4_archive.dump_database', side_effect=lambda target, path: path.write_bytes(b'PGDMP-synthetic')):
        with pytest.raises(InvalidBackupError):
            create_backup(archive_target, backup.backup_dir.parent / 'unsafe', datetime.now(timezone.utc))


def test_backup_rejects_overlap_with_source(archive_target):
    with pytest.raises(InvalidBackupError):
        create_backup(archive_target, archive_target.file_root / 'backup', datetime.now(timezone.utc))


def test_existing_archive_is_never_overwritten(archive_target, backup):
    with pytest.raises(InvalidBackupError):
        create_backup(archive_target, backup.backup_dir, datetime.now(timezone.utc))
    verify_backup(backup.backup_dir)


def test_mock_state_requires_explicit_synthetic_marker(archive_target, tmp_path):
    (archive_target.file_root / 'mock_state.json').write_text('{"real":true}')
    with patch('app.ops.m4_archive.dump_database', side_effect=lambda target, path: path.write_bytes(b'PGDMP-synthetic')):
        with pytest.raises(InvalidBackupError):
            create_backup(archive_target, tmp_path / 'mock-invalid', datetime.now(timezone.utc))
