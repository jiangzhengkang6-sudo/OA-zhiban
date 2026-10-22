"""Synthetic local drill archives; integrity checks are not authenticity signatures."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from uuid import uuid4

from .m4_safety import (ValidatedTarget, UnsafeTargetError, assert_database_container,
                        compose_run, contained_path, revalidate_target)


class InvalidBackupError(ValueError):
    """An archive is incomplete, modified or outside the drill boundary."""


COMPONENTS = {'database', 'attachments', 'knowledge', 'audit_exports', 'config'}
MANAGED = ('attachments', 'knowledge', 'audit_exports')
FORBIDDEN = {'.env', '.git', '.venv', '__pycache__', 'node_modules'}


@dataclass(frozen=True)
class BackupEntry:
    component: str
    relative_path: str
    kind: str
    size: int
    sha256: str


@dataclass(frozen=True)
class BackupManifest:
    version: int
    backup_id: str
    source_identity: str
    captured_at: datetime
    completed_at: datetime
    entries: tuple[BackupEntry, ...]
    backup_dir: Path

    def to_dict(self):
        data = asdict(self)
        del data['backup_dir']
        data['captured_at'] = self.captured_at.isoformat()
        data['completed_at'] = self.completed_at.isoformat()
        return data


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidBackupError('备份时间必须包含时区')
    return value.astimezone(timezone.utc)


def _safe_relative(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise InvalidBackupError('归档相对路径无效')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {'', '.', '..'} for part in value.split('/')):
        raise InvalidBackupError('归档路径必须位于备份目录内')
    if any(part.casefold() in FORBIDDEN or part.casefold().startswith('.env.') for part in path.parts):
        raise InvalidBackupError('归档不得包含密钥或缓存目录')
    if path.suffix.casefold() in {'.pem', '.key', '.pfx', '.p12', '.pyc'}:
        raise InvalidBackupError('归档不得包含密钥或缓存文件')
    return path


def file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _entry(root: Path, path: Path) -> BackupEntry:
    relative = path.relative_to(root).as_posix()
    _safe_relative(relative)
    if path.is_dir():
        return BackupEntry(relative.split('/')[0], relative, 'directory', 0, '')
    return BackupEntry(relative.split('/')[0], relative, 'file', path.stat().st_size, file_hash(path))


def _check_mock(path: Path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('drill_marker') != 'M4_DRILL':
        raise InvalidBackupError('Mock 状态必须显式标记为 M4 合成数据')
    return data


def dump_database(target: ValidatedTarget, destination: Path) -> None:
    assert_database_container(target)
    with destination.open('xb') as stream:
        compose_run(target, ['exec', '-T', 'db', 'pg_dump', '-U', 'oa', '-d', target.database_name,
                             '--format=custom', '--no-owner', '--no-acl'], stdout=stream)


def create_backup(target: ValidatedTarget, output_dir: Path, captured_at: datetime) -> BackupManifest:
    revalidate_target(target)
    source = contained_path(target.file_root)
    output = contained_path(output_dir)
    captured_at = _aware(captured_at)
    if output.is_relative_to(source) or source.is_relative_to(output) or output.exists():
        raise InvalidBackupError('备份目录必须为新的独立目录，禁止覆盖或嵌套源目录')
    if not source.is_dir() or any(not (source / name).is_dir() for name in MANAGED):
        raise InvalidBackupError('缺少明确配置的受管文件目录')
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f'.m4-backup-{uuid4().hex}'
    staging.mkdir()
    try:
        (staging / 'database').mkdir()
        dump_database(target, staging / 'database/postgres.dump')
        if not (staging / 'database/postgres.dump').stat().st_size:
            raise InvalidBackupError('数据库备份为空')
        for name in MANAGED:
            origin = source / name
            paths = [origin, *origin.rglob('*')]
            for path in paths:
                contained_path(path)
                relative = path.relative_to(source).as_posix()
                _safe_relative(relative)
                if not (path.is_dir() or path.is_file()) or (path.is_file() and path.stat().st_nlink != 1):
                    raise InvalidBackupError('受管目录含非普通文件或硬链接')
                dest = staging / relative
                if path.is_dir():
                    dest.mkdir(exist_ok=True, parents=True)
                else:
                    shutil.copyfile(path, dest)
        mock = source / 'mock_state.json'
        if mock.exists():
            contained_path(mock)
            _check_mock(mock)
            (staging / 'mock').mkdir()
            shutil.copyfile(mock, staging / 'mock/state.json')
        (staging / 'config').mkdir()
        (staging / 'config/config.json').write_text(json.dumps({
            'drill_marker': 'M4_DRILL', 'source_identity': target.identity,
            'external_services': 'disabled', 'mock_state_policy': 'explicit-synthetic-marker-only',
        }, indent=2), encoding='utf-8')
        entries = tuple(_entry(staging, path) for path in sorted(staging.rglob('*')))
        manifest = BackupManifest(1, uuid4().hex, target.identity, captured_at,
                                  datetime.now(timezone.utc), entries, staging)
        (staging / 'manifest.json').write_text(json.dumps(manifest.to_dict(), indent=2), encoding='utf-8')
        verify_backup(staging)
        staging.rename(output)
        return verify_backup(output)
    except BaseException:
        # Only remove this invocation's freshly created staging directory.
        contained_path(staging)
        if staging.exists():
            shutil.rmtree(staging)
        raise


def verify_backup(backup_dir: Path) -> BackupManifest:
    try:
        root = contained_path(backup_dir)
        manifest_path = contained_path(root / 'manifest.json')
        if manifest_path.stat().st_size > 16 * 1024 * 1024:
            raise InvalidBackupError('备份清单过大')
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
        if set(data) != {'version', 'backup_id', 'source_identity', 'captured_at', 'completed_at', 'entries'}:
            raise InvalidBackupError('备份清单字段不完整或含未知字段')
        if data['version'] != 1 or not re.fullmatch('[0-9a-f]{32}', data['backup_id']):
            raise InvalidBackupError('不支持的备份版本或标识')
        if not isinstance(data['source_identity'], str) or not data['source_identity'].startswith('oa-m4-'):
            raise InvalidBackupError('备份来源身份无效')
        start, end = (_aware(datetime.fromisoformat(data[key])) for key in ('captured_at', 'completed_at'))
        if start > end:
            raise InvalidBackupError('备份采集时间顺序无效')
        entries = tuple(BackupEntry(**entry) for entry in data['entries'])
        seen = set()
        for entry in entries:
            relative = _safe_relative(entry.relative_path)
            if (entry.component not in COMPONENTS | {'mock'} or relative.parts[0] != entry.component
                    or entry.relative_path.casefold() in seen or type(entry.size) is not int or entry.size < 0):
                raise InvalidBackupError('备份条目组件、大小或唯一性无效')
            seen.add(entry.relative_path.casefold())
            path = contained_path(root / entry.relative_path)
            if entry.kind == 'directory':
                if not path.is_dir() or entry.size != 0 or entry.sha256 != '':
                    raise InvalidBackupError('备份目录条目无效')
            elif entry.kind == 'file':
                if (not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size != entry.size
                        or not re.fullmatch('[0-9a-f]{64}', entry.sha256) or file_hash(path) != entry.sha256):
                    raise InvalidBackupError('备份文件缺失或完整性校验失败')
            else:
                raise InvalidBackupError('备份条目类型无效')
        if not COMPONENTS.issubset({e.component for e in entries}):
            raise InvalidBackupError('备份缺少必要组件')
        if not all(any(e.relative_path == name and e.kind == 'directory' for e in entries) for name in MANAGED):
            raise InvalidBackupError('缺少受管目录组件')
        if not any(e.relative_path == 'database/postgres.dump' and e.kind == 'file' and e.size > 0 for e in entries):
            raise InvalidBackupError('缺少数据库自定义格式备份')
        if not any(e.relative_path == 'config/config.json' and e.kind == 'file' for e in entries):
            raise InvalidBackupError('缺少非敏感配置清单')
        actual = {p.relative_to(root).as_posix().casefold() for p in root.rglob('*')}
        if actual != seen | {'manifest.json'}:
            raise InvalidBackupError('归档包含未列入清单的内容')
        for path in root.rglob('*'):
            contained_path(path)
        if (root / 'mock/state.json').exists():
            _check_mock(root / 'mock/state.json')
        return BackupManifest(1, data['backup_id'], data['source_identity'], start, end, entries, root)
    except InvalidBackupError:
        raise
    except (UnsafeTargetError, OSError, ValueError, TypeError, KeyError):
        raise InvalidBackupError('备份清单或文件无效；未执行恢复') from None
