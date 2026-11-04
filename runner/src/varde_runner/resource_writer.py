"""Periodically write the resource snapshot the CLI budget gate reads."""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from varde_runner.resource_snapshot import sample_resources, write_snapshot

logger = logging.getLogger(__name__)

INTERVAL_S = 15
SNAPSHOT = Path(".cache/data/resources.json")


def snapshot_path(working: Path) -> Path:
    """Return the snapshot path the role-queue CLI reads under ``working``."""
    return working / SNAPSHOT


async def run_snapshot_ticks(
    path: Path,
    agent_rows: Callable[[], list[dict[str, Any]]],
    *,
    interval_s: float = INTERVAL_S,
) -> None:
    """Sample and write the resource snapshot on the lease expiry cadence."""
    previous_cpu_ticks: int | None = None
    previous_taken_at: datetime | None = None
    while True:
        try:
            snapshot, previous_cpu_ticks = sample_resources(
                agent_rows(),
                {},
                previous_cpu_ticks=previous_cpu_ticks,
                previous_taken_at=previous_taken_at,
            )
            previous_taken_at = snapshot.taken_at
            write_snapshot(path, snapshot)
        except Exception:
            logger.exception("resource snapshot tick failed")
        await asyncio.sleep(interval_s)
