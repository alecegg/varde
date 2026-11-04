from datetime import UTC, datetime, timedelta

import pytest
from varde_workflow.role_queue_budget import (
    BudgetLimits,
    ResourceSnapshot,
    may_start,
)

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def snapshot(**changes: object) -> ResourceSnapshot:
    values: dict[str, object] = {
        "taken_at": NOW,
        "providers": {"alpha": 0.5},
        "rss_mb": 100,
        "cpu_pct": 50,
        "processes": 10,
        "live_workers": 2,
    }
    values.update(changes)
    return ResourceSnapshot(**values)  # type: ignore[arg-type]


LIMITS = BudgetLimits(
    provider_max={"alpha": 0.8},
    rss_mb_max=500,
    cpu_pct_max=90,
    processes_max=100,
    global_worker_ceiling=24,
)


def test_allows_snapshot_within_limits() -> None:
    assert may_start(snapshot(), LIMITS, NOW).ok


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"providers": {"alpha": 0.9}}, "provider_max[alpha]"),
        ({"rss_mb": 501}, "rss_mb_max"),
        ({"cpu_pct": 91}, "cpu_pct_max"),
        ({"processes": 101}, "processes_max"),
        ({"live_workers": 24}, "global_worker_ceiling"),
        ({"taken_at": NOW - timedelta(seconds=61)}, "resource snapshot stale"),
    ],
)
def test_rejects_limit_violations(changes: dict[str, object], reason: str) -> None:
    decision = may_start(snapshot(**changes), LIMITS, NOW)
    assert not decision.ok
    assert reason in decision.reason


def test_missing_snapshot_fails_closed() -> None:
    decision = may_start(None, LIMITS, NOW)
    assert not decision.ok
    assert "missing" in decision.reason


def test_unknown_provider_usage_is_skipped() -> None:
    assert may_start(snapshot(providers={}), LIMITS, NOW).ok
