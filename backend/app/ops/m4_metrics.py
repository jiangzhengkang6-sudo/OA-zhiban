"""Recovery metrics require all four measured timezone-aware timestamps."""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil


@dataclass(frozen=True)
class RecoveryMetrics:
    rpo_seconds: int
    rto_seconds: int
    rpo_met: bool
    rto_met: bool


def calculate_recovery_metrics(failure_at, last_verified_commit_at, recovery_started_at, service_verified_at) -> RecoveryMetrics:
    values = (last_verified_commit_at, failure_at, recovery_started_at, service_verified_at)
    if any(not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None for value in values):
        raise ValueError('缺少包含时区的恢复时间证据')
    commit, failure, started, verified = (value.astimezone(timezone.utc) for value in values)
    if not commit <= failure <= started <= verified:
        raise ValueError('恢复时间证据顺序无效')
    rpo = ceil((failure - commit).total_seconds())
    rto = ceil((verified - failure).total_seconds())
    return RecoveryMetrics(rpo, rto, rpo <= 86400, rto <= 900)
