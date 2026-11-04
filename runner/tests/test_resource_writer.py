from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from varde_runner import resource_writer
from varde_runner.resource_writer import run_snapshot_ticks, snapshot_path
from varde_workflow.commands import plan_queue_roles
from varde_workflow.role_queue_budget import (
    BudgetLimits,
    ResourceSnapshot,
    may_start,
)

LIMITS = BudgetLimits(
    provider_max={},
    rss_mb_max=float("inf"),
    cpu_pct_max=float("inf"),
    processes_max=2**31 - 1,
    global_worker_ceiling=24,
)


def _snapshot(taken_at: datetime) -> ResourceSnapshot:
    return ResourceSnapshot(taken_at, {}, 12.0, 3.0, 40, 0)


def test_writer_path_equals_reader_path() -> None:
    assert snapshot_path(Path("/work")) == Path("/work") / plan_queue_roles._SNAPSHOT


def test_tick_writes_snapshot_the_cli_budget_gate_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = snapshot_path(tmp_path)
    intervals: list[float] = []

    async def stop_after_first(seconds: float) -> None:
        intervals.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(resource_writer.asyncio, "sleep", stop_after_first)
    rows: list[dict[str, Any]] = [
        {"lifecycle": "running"},
        {"lifecycle": "completed"},
    ]
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_snapshot_ticks(path, lambda: rows))

    assert intervals == [15]
    assert path.is_file()
    assert list(path.parent.glob(f".{path.name}.*")) == []
    now = datetime.now(UTC)
    snapshot = plan_queue_roles._snapshot(tmp_path)
    assert snapshot is not None
    assert now - snapshot.taken_at < timedelta(seconds=60)
    assert snapshot.providers == {}
    assert snapshot.live_workers == 1
    assert may_start(snapshot, LIMITS, now).ok


def test_sampler_exception_does_not_stop_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = snapshot_path(tmp_path)
    calls: list[dict[str, Any]] = []
    real_sample = resource_writer.sample_resources

    def fails_once(*args: Any, **kwargs: Any):
        calls.append(kwargs)
        if len(calls) == 1:
            raise OSError("temporary sampler failure")
        return real_sample(*args, **kwargs)

    sleeps = 0

    async def stop_after_second(_seconds: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if len(calls) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(resource_writer, "sample_resources", fails_once)
    monkeypatch.setattr(resource_writer.asyncio, "sleep", stop_after_second)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_snapshot_ticks(path, list))

    assert len(calls) == 2
    assert sleeps == 2
    assert path.is_file()


def test_each_tick_passes_the_previous_cpu_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = snapshot_path(tmp_path)
    first = _snapshot(datetime(2026, 1, 2, tzinfo=UTC))
    second = _snapshot(datetime(2026, 1, 2, 0, 0, 15, tzinfo=UTC))
    results = [(first, 100), (second, 175)]
    seen: list[tuple[int | None, datetime | None]] = []

    def fake_sample(
        _rows: list[dict[str, Any]],
        _providers: dict[str, float],
        *,
        previous_cpu_ticks: int | None = None,
        previous_taken_at: datetime | None = None,
    ) -> tuple[ResourceSnapshot, int]:
        seen.append((previous_cpu_ticks, previous_taken_at))
        return results[len(seen) - 1]

    async def stop_after_second(_seconds: float) -> None:
        if len(seen) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(resource_writer, "sample_resources", fake_sample)
    monkeypatch.setattr(resource_writer.asyncio, "sleep", stop_after_second)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_snapshot_ticks(path, list))

    assert seen == [(None, None), (100, first.taken_at)]
    assert plan_queue_roles._snapshot(tmp_path) == second
