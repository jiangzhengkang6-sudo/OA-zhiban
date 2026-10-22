"""Fail-closed validation for local M4 drill targets."""

from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import subprocess
import tempfile


M4_DRILL_ROOT = Path(__file__).resolve().parents[3] / "data" / "m4-drills"


class UnsafeTargetError(ValueError):
    """Raised when a drill target cannot be proven to be isolated."""


@dataclass(frozen=True)
class DrillTarget:
    compose_project: str
    database_host: str
    database_name: str
    volume_name: str
    file_root: Path
    drill_marker: str
    source_identity: str | None = None
    volume_owner_project: str | None = None


@dataclass(frozen=True)
class ValidatedTarget:
    compose_project: str
    database_host: str
    database_name: str
    volume_name: str
    file_root: Path
    identity: str


def _identity(project: str, host: str, database: str, volume: str, root: Path) -> str:
    normalized_root = root.as_posix().casefold()
    return "/".join((project.casefold(), host.casefold(), database.casefold(), volume.casefold(), normalized_root))


def validate_drill_target(target: DrillTarget) -> ValidatedTarget:
    if not isinstance(target, DrillTarget):
        raise UnsafeTargetError("演练目标配置类型无效")
    if target.drill_marker != "M4_DRILL":
        raise UnsafeTargetError("缺少有效的 M4 演练标记")
    if not re.fullmatch(r"oa-m4-[a-z0-9]+(?:-[a-z0-9]+)*", target.compose_project):
        raise UnsafeTargetError("Compose project 不在 M4 隔离白名单")
    if target.database_host != "m4-db" or not re.fullmatch(r"oa_m4_[a-z0-9_]+_test", target.database_name):
        raise UnsafeTargetError("数据库目标不在 M4 测试白名单")
    if not target.volume_name.startswith(f"{target.compose_project}-"):
        raise UnsafeTargetError("持久化卷不属于指定 M4 project")
    if target.volume_owner_project and target.volume_owner_project != target.compose_project:
        raise UnsafeTargetError("持久化卷已被其他 project 占用")

    allowed_root = Path(M4_DRILL_ROOT).resolve()
    file_root = Path(target.file_root).resolve()
    try:
        relative_root = file_root.relative_to(allowed_root)
    except ValueError as exc:
        raise UnsafeTargetError("文件目录超出 M4 演练白名单") from exc
    if not relative_root.parts or any(part in {".", ".."} for part in relative_root.parts):
        raise UnsafeTargetError("文件目录必须是 M4 演练根目录下的独立子目录")

    identity = _identity(
        target.compose_project,
        target.database_host,
        target.database_name,
        target.volume_name,
        file_root,
    )
    if target.source_identity and target.source_identity.casefold() == identity:
        raise UnsafeTargetError("源与目标身份重复")

    return ValidatedTarget(
        compose_project=target.compose_project,
        database_host=target.database_host,
        database_name=target.database_name,
        volume_name=target.volume_name,
        file_root=file_root,
        identity=identity,
    )


def revalidate_target(target: ValidatedTarget) -> ValidatedTarget:
    if not isinstance(target, ValidatedTarget):
        raise UnsafeTargetError('必须提供经验证的演练目标')
    checked = validate_drill_target(DrillTarget(target.compose_project, target.database_host,
        target.database_name, target.volume_name, target.file_root, 'M4_DRILL'))
    if checked != target:
        raise UnsafeTargetError('演练目标身份已变化')
    return checked


def contained_path(path: Path) -> Path:
    """Reject links before resolving, including Windows directory junctions."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise UnsafeTargetError('演练路径不允许符号链接或目录联接')
    root = Path(M4_DRILL_ROOT).resolve()
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise UnsafeTargetError('文件目录超出 M4 演练白名单')
    return resolved


def compose_run(target: ValidatedTarget, args: list[str], **kwargs):
    revalidate_target(target)
    project_root = Path(__file__).resolve().parents[3]
    # Never load a developer .env or inherit provider settings into a drill.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE',
                              'PROGRAMDATA', 'PROGRAMFILES', 'APPDATA', 'LOCALAPPDATA', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG'}}
    env.update(POSTGRES_PASSWORD='M4-Synthetic-Only-4917', M4_DATABASE_NAME=target.database_name,
        M4_DATABASE_URL=f'postgresql+asyncpg://oa:M4-Synthetic-Only-4917@m4-db/{target.database_name}',
        M4_DATABASE_SYNC_URL=f'postgresql+psycopg://oa:M4-Synthetic-Only-4917@m4-db/{target.database_name}',
        M4_CHECKPOINTER_URL=f'postgresql://oa:M4-Synthetic-Only-4917@m4-db/{target.database_name}')
    with tempfile.TemporaryDirectory(prefix='m4-compose-') as temporary:
        env_file = Path(temporary) / 'synthetic.env'
        env_file.touch()
        command = ['docker', 'compose', '--env-file', str(env_file), '-p', target.compose_project,
                   '-f', str(project_root / 'docker-compose.yml'),
                   '-f', str(project_root / 'docker-compose.m4.yml'), *args]
        try:
            result = subprocess.run(command, cwd=project_root, env=env, stderr=subprocess.PIPE,
                                    timeout=kwargs.pop('timeout', 120), **kwargs)
        except (subprocess.SubprocessError, OSError):
            raise UnsafeTargetError('M4 隔离命令执行失败；请检查 Docker 状态') from None
    if result.returncode:
        raise UnsafeTargetError('M4 隔离命令未成功；未记录凭据或原始错误输出')
    return result


def assert_database_container(target: ValidatedTarget) -> None:
    result = compose_run(target, ['ps', '-q', 'db'], stdout=subprocess.PIPE)
    container_id = result.stdout.decode().strip()
    if not re.fullmatch(r'[0-9a-f]{12,64}', container_id):
        raise UnsafeTargetError('未找到唯一的 M4 数据库容器')
    result = subprocess.run(['docker', 'inspect', container_id], capture_output=True, timeout=30)
    if result.returncode:
        raise UnsafeTargetError('不能验证 M4 数据库容器身份')
    try:
        record, = json.loads(result.stdout)
        labels = record['Config']['Labels']
        environment = dict(item.split('=', 1) for item in record['Config']['Env'] if '=' in item)
        volumes = [m['Name'] for m in record['Mounts'] if m['Type'] == 'volume']
        valid = (labels.get('com.docker.compose.project') == target.compose_project
                 and labels.get('com.docker.compose.service') == 'db'
                 and environment.get('POSTGRES_DB') == target.database_name
                 and record['Config']['Hostname'] == 'm4-db'
                 and volumes == [target.volume_name]
                 and record['State']['Running'])
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise UnsafeTargetError('M4 数据库容器、数据库名或持久化卷身份不匹配')
