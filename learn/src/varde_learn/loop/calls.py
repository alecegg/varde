"""Append and summarize command call records."""

from __future__ import annotations

import contextlib
import math
import os
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from varde_data.calls import open_calls
from varde_data.errors import Invalid, LearnStoreIo
from varde_data.repos.calls import CALLS_NAME  # noqa: F401 - re-exported

from .errors import StoreConfig, StoreIo
from .store.paths import resolve_store_dir

DROPPED_LOG_NAME = "cli_calls.dropped.log"
DROPPED_LOG_MAX_BYTES = 1_000_000
CAP_MARKER = b"cap reached: further drops are counted in-process only\n"
_dropped = 0
SUCCESS = "success"
FAILURE = "failure"
BLOCKED = "blocked"


class CallRow(TypedDict):
    """One CLI invocation in the calls store."""

    ts: str
    command: str
    status: str
    duration_s: float
    session: str | None
    guardrail: NotRequired[str]
    retry: NotRequired[bool]
    arg: NotRequired[str]


class RankRow(TypedDict):
    key: str | None
    calls: int
    failures: int
    retries: int
    failure_rate: float
    retry_rate: float


def append_call(row: CallRow, store_dir: Path | None = None) -> bool:
    """Append a call row; return false if unavailable.

    Never raises. A dropped call is counted and logged, so drops stay visible.
    """
    root: Path | None = None
    try:
        root = store_dir or resolve_store_dir()
        open_calls(root).append(row)
    except Exception as error:  # noqa: BLE001 - telemetry must never change the CLI outcome.
        _record_drop(root, error)
        return False
    return True


def dropped_calls() -> int:
    """Return how many calls this process failed to record."""
    return _dropped


def _record_drop(root: Path | None, error: Exception) -> None:
    global _dropped  # noqa: PLW0603 - process-wide counter of lost telemetry.
    _dropped += 1
    if root is None:
        return
    when = datetime.now(UTC).isoformat()
    line = f"{when}\t{type(error).__name__}: {error}".replace("\n", " ") + "\n"
    with contextlib.suppress(Exception):  # the drop log is best effort too.
        _append_drop_line(root / DROPPED_LOG_NAME, line.encode())


def _append_drop_line(path: Path, line: bytes) -> None:
    size = path.stat().st_size if path.exists() else 0
    if size and _ends_with(path, CAP_MARKER):
        return
    if size + len(line) > DROPPED_LOG_MAX_BYTES:
        line = CAP_MARKER
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, line)
    finally:
        os.close(descriptor)


def _ends_with(path: Path, suffix: bytes) -> bool:
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - len(suffix)))
        return handle.read().endswith(suffix)


def read_calls(store_dir: Path | None = None) -> list[CallRow]:
    """Read valid call rows, ignoring missing, malformed, or incomplete lines."""
    try:
        return read_calls_strict(store_dir)
    except OSError, UnicodeDecodeError, StoreConfig, StoreIo, Invalid:
        return []


def read_calls_strict(
    store_dir: Path | None = None, *, since: datetime | None = None
) -> list[CallRow]:
    """Read valid rows and propagate store access errors to interactive callers.

    With ``since``, the store returns a superset by a coarse bound and rows
    older than ``since`` (by parsed ``ts``) are dropped here.
    """
    root = store_dir or resolve_store_dir()
    try:
        stored = open_calls(root).read_strict(since)
    except LearnStoreIo as error:
        raise StoreIo(error.operation, error.path, error.source) from error
    rows = [cast("CallRow", row) for row in stored if _valid_row(row)]
    if since is None:
        return rows
    return [
        row for row in rows if (when := parse_timestamp(row["ts"])) and when >= since
    ]


def _valid_row(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    timestamp = value.get("ts")
    if (
        not all(
            isinstance(value.get(key), str) and value[key]
            for key in ("ts", "command", "status")
        )
        or not isinstance(timestamp, str)
        or parse_timestamp(timestamp) is None
    ):
        return False
    if value["status"] not in (SUCCESS, FAILURE, BLOCKED):
        return False
    duration = value.get("duration_s")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return False
    if duration < 0 or not math.isfinite(duration):
        return False
    if value.get("session") is not None and not isinstance(value["session"], str):
        return False
    if "arg" in value and not isinstance(value["arg"], str):
        return False
    return "guardrail" not in value or isinstance(value["guardrail"], str)


def mark_retries(rows: list[CallRow], window_s: float = 120) -> list[CallRow]:
    """Copy rows with retry flags for failed same-command calls in the window."""
    parsed = [
        (index, row, when)
        for index, row in enumerate(rows)
        if "guardrail" not in row and (when := parse_timestamp(row["ts"])) is not None
    ]
    ordered = sorted(parsed, key=lambda item: (item[2], item[0]))
    latest_failure: dict[tuple[str, str], datetime] = {}
    retry_flags = [False] * len(rows)
    for index, row, when in ordered:
        session = row.get("session")
        if session is None or "guardrail" in row:
            continue
        key = (session, row["command"])
        prior = latest_failure.get(key)
        retry_flags[index] = (
            prior is not None and 0 <= (when - prior).total_seconds() <= window_s
        )
        if row["status"] == FAILURE:
            latest_failure[key] = when
    return [{**row, "retry": retry_flags[index]} for index, row in enumerate(rows)]


def parse_timestamp(value: str) -> datetime | None:
    """Parse a timestamp as an aware UTC datetime."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def rank_commands(rows: list[CallRow]) -> dict[str, list[RankRow]]:
    """Rank user calls by failure and retry rate; guardrail rows are telemetry."""
    marked = [
        row
        for row in mark_retries(rows)
        if "guardrail" not in row and row["status"] != BLOCKED
    ]
    groups: dict[str, dict[str | None, list[CallRow]]] = {
        "commands": defaultdict(list),
        "sessions": defaultdict(list),
        "weeks": defaultdict(list),
    }
    for row in marked:
        groups["commands"][row["command"]].append(row)
        groups["sessions"][row.get("session")].append(row)
        when = parse_timestamp(row["ts"])
        if when is not None:
            iso_year, iso_week, _ = when.astimezone(UTC).isocalendar()
            groups["weeks"][f"{iso_year}-W{iso_week:02d}"].append(row)
    return {name: _rank_groups(grouped) for name, grouped in groups.items()}


def _rank_groups(groups: dict[str | None, list[CallRow]]) -> list[RankRow]:
    result: list[RankRow] = []
    for key, items in groups.items():
        count = len(items)
        failures = sum(row["status"] == FAILURE for row in items)
        retries = sum(row.get("retry", False) for row in items)
        result.append(
            {
                "key": key,
                "calls": count,
                "failures": failures,
                "retries": retries,
                "failure_rate": failures / count,
                "retry_rate": retries / count,
            }
        )
    return sorted(
        result,
        key=lambda item: (
            -item["failure_rate"],
            -item["retry_rate"],
            (item["key"] is None, item["key"] or ""),
        ),
    )


def parse_window(value: str) -> timedelta:
    """Parse a positive integer duration such as 30d or 2h."""
    match = re.fullmatch(r"([0-9]+)([dhms])", value)
    if match is None or int(match[1]) <= 0:
        raise ValueError("window must be a positive duration such as 30d or 2h")
    return timedelta(
        seconds=int(match[1]) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[match[2]]
    )


HARNESS_SESSION_VARS = (
    "CLAUDE_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_THREAD_ID",
)
SESSION_VARS = (*HARNESS_SESSION_VARS, "VARDE_TOZ_SESSION")


def session_id() -> str | None:
    """Return the active harness session identifier, if available.

    Pi and OpenCode export no session variable, so their rows stay null.
    """
    return next(
        (os.environ[name] for name in SESSION_VARS if os.environ.get(name)),
        None,
    )


TOOL_COMMAND = "tool"


def tool_call_row(
    skill: str, step: str, *, status: str, duration_s: float, session: str | None
) -> CallRow:
    """The counter row for one call of an extracted step tool."""
    return {
        "ts": datetime.now(UTC).isoformat(),
        "command": f"{TOOL_COMMAND} {skill}",
        "status": status,
        "duration_s": max(0.0, duration_s),
        "session": session,
        "arg": f"{skill}/{step}",
    }


def append_tool_call(
    skill: str,
    step: str,
    *,
    status: str,
    duration_s: float,
    store_dir: Path | None = None,
) -> bool:
    """Count one call of an extracted step tool; false if the store was unavailable."""
    row = tool_call_row(
        skill, step, status=status, duration_s=duration_s, session=session_id()
    )
    return append_call(row, store_dir)
