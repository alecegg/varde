"""Read and persist a lightweight runner resource snapshot."""

import json
import os
import resource
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_workflow.role_queue_budget import ResourceSnapshot

from varde_runner.instance_cap import live_count


def _cpu_ticks() -> int:
    if sys.platform == "darwin":
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return int((usage.ru_utime + usage.ru_stime) * 1_000_000)
    with Path("/proc/stat").open(encoding="ascii") as stat_file:
        fields = stat_file.readline().split()[1:]
    return sum(map(int, fields))


def _cpu_percentage(delta: int, elapsed: float) -> float:
    if sys.platform == "darwin":
        return max(0.0, delta / 1_000_000 / elapsed * 100)
    return max(0.0, delta / (os.cpu_count() or 1) / elapsed * 100)


def _rss_mb() -> float:
    if Path("/proc/self/statm").exists():
        pages = int(Path("/proc/self/statm").read_text(encoding="ascii").split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return usage.ru_maxrss / divisor


def sample_resources(
    agent_rows: list[dict[str, Any]],
    providers: dict[str, float] | None = None,
    *,
    previous_cpu_ticks: int | None = None,
    previous_taken_at: datetime | None = None,
    now: datetime | None = None,
) -> tuple[ResourceSnapshot, int]:
    """Sample runner process and host counts; return snapshot and CPU baseline."""
    taken_at = now or datetime.now(UTC)
    cpu_ticks = _cpu_ticks()
    elapsed = (taken_at - previous_taken_at).total_seconds() if previous_taken_at else 0
    cpu_pct = 0.0
    if previous_cpu_ticks is not None and elapsed > 0 and cpu_ticks:
        cpu_pct = _cpu_percentage(cpu_ticks - previous_cpu_ticks, elapsed)

    if Path("/proc/self/statm").exists():
        rss_mb = _rss_mb()
        processes = sum(entry.name.isdecimal() for entry in Path("/proc").iterdir())
    else:
        rss_mb = _rss_mb()
        processes = 1
    return (
        ResourceSnapshot(
            taken_at,
            providers or {},
            rss_mb,
            cpu_pct,
            processes,
            live_count(agent_rows),
        ),
        cpu_ticks,
    )


def write_snapshot(path: Path, snapshot: ResourceSnapshot) -> None:
    """Atomically replace the resource snapshot JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "taken_at": snapshot.taken_at.isoformat(),
        "providers": snapshot.providers,
        "rss_mb": snapshot.rss_mb,
        "cpu_pct": snapshot.cpu_pct,
        "processes": snapshot.processes,
        "live_workers": snapshot.live_workers,
    }
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
