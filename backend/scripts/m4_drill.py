"""Explicit, local-only M4 drill commands. Never reads application .env files."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ops.m4_archive import InvalidBackupError, create_backup, verify_backup
from app.ops.m4_metrics import calculate_recovery_metrics
from app.ops.m4_restore import restore_backup
from app.ops.m4_safety import DrillTarget, UnsafeTargetError, contained_path, validate_drill_target


def read_config(path):
    file = contained_path(Path(path))
    data = json.loads(file.read_text(encoding='utf-8'))
    if set(data) != {'target', 'backup_dir'}:
        raise UnsafeTargetError('配置只允许演练目标与归档路径，不得放入密钥')
    target_data = dict(data['target'])
    target_data['file_root'] = Path(target_data['file_root'])
    target = validate_drill_target(DrillTarget(**target_data))
    return target, contained_path(Path(data['backup_dir']))


def main(argv=None):
    parser = argparse.ArgumentParser(description='M4 synthetic isolated backup and recovery')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('validate', 'backup', 'verify', 'restore', 'report'):
        command = commands.add_parser(name)
        command.add_argument('--config', required=True, help='Explicit synthetic JSON config below data/m4-drills')
        if name == 'restore':
            command.add_argument('--source', required=True, help='Explicit source config')
            command.add_argument('--destination', required=True, help='Explicit empty destination config')
        if name == 'report':
            command.add_argument('--evidence', required=True, help='JSON with four measured timestamps')
    args = parser.parse_args(argv)
    try:
        target, archive = read_config(args.config)
        if args.command == 'validate':
            result = {'status': 'validated', 'identity': target.identity}
        elif args.command in {'backup', 'verify'}:
            backup = (create_backup(target, archive, datetime.now(timezone.utc))
                      if args.command == 'backup' else verify_backup(archive))
            if backup.source_identity != target.identity:
                raise InvalidBackupError('备份来源与显式配置不匹配')
            result = {'status': 'verified', 'backup_id': backup.backup_id}
        elif args.command == 'restore':
            source, source_archive = read_config(args.source)
            destination, _ = read_config(args.destination)
            if source != target or source_archive != archive:
                raise UnsafeTargetError('主配置与源配置不一致')
            restored = restore_backup(verify_backup(archive), source, destination)
            result = {'status': 'restored', 'backup_id': restored.backup_id,
                      'destination_identity': restored.destination_identity}
        else:
            evidence = json.loads(contained_path(Path(args.evidence)).read_text(encoding='utf-8'))
            keys = ('failure_at', 'last_verified_commit_at', 'recovery_started_at', 'service_verified_at')
            metrics = calculate_recovery_metrics(*(datetime.fromisoformat(evidence[key]) for key in keys))
            result = {'status': 'measured', **asdict(metrics)}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError):
        print(json.dumps({'status': 'failed', 'message': '演练检查或执行失败；未覆盖项不得标记通过'}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
