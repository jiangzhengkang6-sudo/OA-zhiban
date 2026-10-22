"""Fail-closed validation for local M4 drill targets."""

from dataclasses import dataclass
from pathlib import Path
import re


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
