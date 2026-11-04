"""Durable record of the host and tracked process groups, and stale-group reaping."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_runner.plugins.process_state import (
    inspect_process,
    process_group_exists,
    wait_for_group_exit,
    write_state,
)

logger = logging.getLogger(__name__)

REAP_TIMEOUT_S = 2.0


@dataclass(frozen=True, slots=True)
class GroupRecord:
    pid: int
    process_group: int
    started_at: str | None = None
    command: list[str] | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "process_group": self.process_group,
            "started_at": self.started_at,
            "command": self.command,
        }


def identify_group(
    pid: int, process_group: int, command: list[str] | None = None
) -> GroupRecord:
    """Record a group leader with its ps start time; blocking, call from a thread."""
    try:
        identity = inspect_process(pid, "node host")
    except OSError, RuntimeError, ValueError, subprocess.SubprocessError:
        identity = None
    started_at = identity.start_time if identity else None
    return GroupRecord(pid, process_group, started_at, command)


def write_record(
    path: Path, host: GroupRecord | None, tracked: list[GroupRecord]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_state(
        path,
        {
            "host": host.as_json() if host else None,
            "tracked": [entry.as_json() for entry in tracked],
        },
    )


def clear_record(path: Path) -> None:
    path.unlink(missing_ok=True)


def _group_from_json(value: object) -> GroupRecord | None:
    if not isinstance(value, dict):
        return None
    pid, group = value.get("pid"), value.get("process_group")
    started_at, command = value.get("started_at"), value.get("command")
    if not (isinstance(pid, int) and isinstance(group, int) and group > 1):
        return None
    if not (started_at is None or isinstance(started_at, str)):
        return None
    if not (command is None or isinstance(command, list)):
        return None
    return GroupRecord(pid, group, started_at, command)


def read_record(path: Path) -> list[GroupRecord]:
    """Return host then tracked groups; an unreadable record yields none."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return []
    if not isinstance(value, dict):
        return []
    entries = [value.get("host"), *(value.get("tracked") or [])]
    groups = [_group_from_json(entry) for entry in entries if entry is not None]
    return [group for group in groups if group is not None]


def _leader_matches(group: GroupRecord) -> bool:
    """True when the leader is gone or keeps its recorded identity; unknown is False."""
    try:
        identity = inspect_process(group.pid, "node host")
    except OSError, RuntimeError, ValueError, subprocess.SubprocessError:
        return False
    if identity is None:
        return True
    if group.started_at is None or identity.start_time != group.started_at:
        return False
    return all(arg in identity.command for arg in group.command or [])


def _signal_group(process_group: int, sig: int) -> None:
    try:
        os.killpg(process_group, sig)
    except ProcessLookupError, PermissionError:
        return


async def _reap_group(group: GroupRecord) -> bool:
    if not process_group_exists(group.process_group):
        return True
    if not await asyncio.to_thread(_leader_matches, group):
        logger.warning(
            "node_host_orphan_skipped group=%s reason=identity_changed",
            group.process_group,
        )
        return False
    for sig in (signal.SIGTERM, signal.SIGKILL):
        _signal_group(group.process_group, sig)
        if await wait_for_group_exit(
            group.process_group, REAP_TIMEOUT_S, process_group_exists
        ):
            return True
    logger.warning("node_host_orphan_survived group=%s", group.process_group)
    return False


async def reap_orphans(path: Path) -> list[int]:
    """Kill recorded stale groups whose identity still matches; return their ids."""
    reaped, survivors = [], 0
    for group in read_record(path):
        if group.process_group > 1 and await _reap_group(group):
            reaped.append(group.process_group)
        else:
            survivors += 1
    if not survivors:
        clear_record(path)
    return reaped
