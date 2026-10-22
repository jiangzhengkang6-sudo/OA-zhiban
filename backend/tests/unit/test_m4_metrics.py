from datetime import datetime, timedelta, timezone

import pytest

from app.ops.m4_metrics import calculate_recovery_metrics


@pytest.mark.parametrize('rpo,rto,passes', [(0,0,True), (86400,900,True), (86401,901,False), (1,1,True)])
def test_recovery_metric_boundaries(rpo, rto, passes):
    failure = datetime(2026, 10, 22, tzinfo=timezone.utc)
    result = calculate_recovery_metrics(failure, failure-timedelta(seconds=rpo), failure,
                                        failure+timedelta(seconds=rto))
    assert (result.rpo_seconds, result.rto_seconds) == (rpo, rto)
    assert result.rpo_met == result.rto_met == passes


def test_rto_includes_time_before_recovery_started():
    failure = datetime(2026, 10, 22, tzinfo=timezone.utc)
    result = calculate_recovery_metrics(failure, failure, failure+timedelta(seconds=60), failure+timedelta(seconds=90))
    assert result.rto_seconds == 90


@pytest.mark.parametrize('index,value', [(0,None), (1,None), (2,None), (3,None),
                                       (0,datetime(2026,10,22))])
def test_missing_or_naive_time_is_not_reported_as_passed(index,value):
    values = [datetime(2026,10,22,tzinfo=timezone.utc)] * 4
    values[index] = value
    with pytest.raises(ValueError):
        calculate_recovery_metrics(*values)


@pytest.mark.parametrize('offsets', [(0,1,2,3), (1,0,0,3), (1,0,3,2)])
def test_invalid_time_order_is_rejected(offsets):
    now = datetime(2026,10,22,tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        calculate_recovery_metrics(*(now+timedelta(seconds=n) for n in offsets))


def test_fractional_seconds_are_rounded_up():
    now = datetime(2026,10,22,tzinfo=timezone.utc)
    result = calculate_recovery_metrics(now, now-timedelta(microseconds=1), now, now+timedelta(microseconds=1))
    assert result.rpo_seconds == result.rto_seconds == 1
