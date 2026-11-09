"""Wrap an existing trusted backup command and persist a verified artifact receipt.

Example: --artifact /private/oa.dump -- pg_dump --file=/private/oa.dump
The command must create a NEW artifact. Configure DB credentials via PGPASSFILE.
"""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import get_settings
from app.ops.operations_monitor import atomic_json, exclusive, stamp, utcnow


def run_backup(settings, artifact, command):
    artifact = Path(artifact).resolve()
    root = Path(settings.ops_state_dir).resolve()
    with exclusive(root / 'backup.lock'):
        receipt = dict(version=1, tenant_id=settings.auth_tenant_id, status='RUNNING', started_at=stamp(utcnow()))
        atomic_json(root / 'backup.json', receipt)
        try:
            if not command or artifact.exists() or artifact.is_relative_to(root):
                raise ValueError('Use a new artifact outside the monitoring state directory')
            result = subprocess.run(command, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    timeout=settings.ops_backup_max_runtime_seconds)
            if result.returncode != 0 or not artifact.is_file() or artifact.stat().st_size == 0:
                raise ValueError('Backup command or artifact failed')
            with artifact.open('rb') as stream:
                checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            receipt.update(status='SUCCESS', completed_at=stamp(utcnow()),
                           artifact_bytes=artifact.stat().st_size, artifact_sha256=checksum)
        except Exception:
            receipt.update(status='FAILED', completed_at=stamp(utcnow()))
        atomic_json(root / 'backup.json', receipt)
        return receipt['status'] == 'SUCCESS'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    try:
        success = run_backup(get_settings(), args.artifact, command)
    except Exception:
        print('备份未启动；请检查目标文件、命令和任务锁', file=sys.stderr)
        sys.exit(2)
    print('备份成功并已记录文件校验' if success else '备份失败，已记录故障')
    sys.exit(0 if success else 1)
