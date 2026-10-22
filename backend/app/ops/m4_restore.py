"""Restore only into an independent empty synthetic drill target."""

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from .m4_archive import BackupManifest, InvalidBackupError, verify_backup
from .m4_safety import (ValidatedTarget, UnsafeTargetError, assert_database_container,
                        compose_run, contained_path, revalidate_target)


@dataclass(frozen=True)
class RestoreCheck:
    component: str
    passed: bool


@dataclass(frozen=True)
class RestoreResult:
    backup_id: str
    destination_identity: str
    checks: tuple[RestoreCheck, ...]

    @property
    def success(self):
        return bool(self.checks) and all(check.passed for check in self.checks)


def database_is_empty(target: ValidatedTarget) -> bool:
    query = """SELECT
        (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
         AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass
                         AND d.objid=c.oid AND d.deptype='e')) +
        (SELECT count(*) FROM pg_namespace WHERE nspname NOT LIKE 'pg_%'
         AND nspname NOT IN ('public','information_schema')) +
        (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
         WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
         AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass
                         AND d.objid=p.oid AND d.deptype='e'));"""
    result = compose_run(target, ['exec', '-T', 'db', 'psql', '-U', 'oa', '-d',
        target.database_name, '-X', '-v', 'ON_ERROR_STOP=1', '-Atc', query], stdout=subprocess.PIPE)
    return result.stdout.strip() == b'0'


def restore_database(target: ValidatedTarget, archive: Path) -> None:
    with archive.open('rb') as stream:
        compose_run(target, ['exec', '-T', 'db', 'pg_restore', '-U', 'oa', '-d', target.database_name,
            '--single-transaction', '--exit-on-error', '--no-owner', '--no-acl'], stdin=stream,
            stdout=subprocess.PIPE)


def restore_backup(backup: BackupManifest, source: ValidatedTarget, destination: ValidatedTarget) -> RestoreResult:
    revalidate_target(source)
    revalidate_target(destination)
    source_root = contained_path(source.file_root)
    dest_root = contained_path(destination.file_root)
    if (source.compose_project == destination.compose_project or source.volume_name == destination.volume_name
            or source_root.is_relative_to(dest_root) or dest_root.is_relative_to(source_root)):
        raise UnsafeTargetError('恢复目标必须使用不同 project、持久化卷及互不嵌套的文件目录')
    checked = verify_backup(backup.backup_dir)
    if checked != backup or checked.source_identity != source.identity:
        raise InvalidBackupError('备份来源或清单已变化')
    if (dest_root.is_relative_to(checked.backup_dir) or checked.backup_dir.is_relative_to(dest_root)):
        raise UnsafeTargetError('恢复目标不得覆盖备份目录')
    if dest_root.exists() and (not dest_root.is_dir() or any(dest_root.iterdir())):
        raise UnsafeTargetError('恢复文件目标必须为空，禁止覆盖已有内容')
    assert_database_container(destination)
    if not database_is_empty(destination):
        raise UnsafeTargetError('恢复数据库包含已有对象；请另建独立空目标')
    # Prepare files before mutating the database; retain failed DB for investigation.
    dest_root.parent.mkdir(parents=True, exist_ok=True)
    staging = dest_root.parent / f'.m4-restore-{uuid4().hex}'
    staging.mkdir()
    try:
        for entry in checked.entries:
            if entry.component == 'database':
                continue
            relative = 'mock_state.json' if entry.relative_path == 'mock/state.json' else entry.relative_path
            if entry.relative_path == 'mock':
                continue
            dest = staging / relative
            if entry.kind == 'directory':
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(checked.backup_dir / entry.relative_path, dest)
        # Recheck just before the first database write.
        verify_backup(checked.backup_dir)
        assert_database_container(destination)
        if not database_is_empty(destination):
            raise UnsafeTargetError('恢复前目标库已不再为空')
        restore_database(destination, checked.backup_dir / 'database/postgres.dump')
        if dest_root.exists():
            dest_root.rmdir()
        staging.rename(dest_root)
    finally:
        if staging.exists():
            contained_path(staging)
            shutil.rmtree(staging)
    return RestoreResult(checked.backup_id, destination.identity,
        tuple(RestoreCheck(component, True) for component in sorted({e.component for e in checked.entries})))
