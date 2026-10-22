"""Small deterministic baseline; full load tests belong in a dedicated environment."""

import json
import statistics
import time

import pytest

from app.adapters.mock_adapter import MockAdapter


@pytest.mark.performance
def test_mock_provider_read_p95_baseline(capsys):
    adapter = MockAdapter()
    samples = []
    for _ in range(100):
        started = time.perf_counter()
        adapter.get_user_context("u_emp_001")
        samples.append((time.perf_counter() - started) * 1000)
    p95 = sorted(samples)[94]
    report = {"operation": "mock_identity_read", "samples": len(samples), "p95_ms": round(p95, 3), "mean_ms": round(statistics.mean(samples), 3)}
    print(json.dumps(report, ensure_ascii=False))
    assert p95 < 100

