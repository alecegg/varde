"""Summarize runner tool calls by session role."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from varde_core.envelope import success, tool_error

from .calls import parse_timestamp, parse_window
from .help import help_text

SOURCE = "varde learn tools --by-role"
_WINDOW_START = re.compile(r"(?:^|\s)tool-stats-window-start=([^\s]+)")
_FAILURE_COUNT = re.compile(r"(?:^|\s)tool-stats-failures=(\d+)(?:\s|$)")


def runner_database() -> Path:
    working = os.environ.get("VARDE_WORKING_DIR")
    if not working:
        raise ValueError("VARDE_WORKING_DIR must point to a Varde working directory")
    return Path(working) / ".cache" / "dashboard" / "runner.sqlite3"


def summarize(database: Path, since: str | None = None) -> dict[str, Any]:
    cutoff = datetime.now(UTC) - parse_window(since) if since else None
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        sessions = {
            row["id"]: row["role"]
            for row in connection.execute("SELECT id, role FROM sessions")
        }
        events = connection.execute(
            "SELECT session_id, kind, payload, created_at FROM events "
            "WHERE kind IN ('tool_intent', 'tool_result') ORDER BY seq"
        ).fetchall()
    finally:
        connection.close()

    pending: dict[tuple[str, str], dict[str, Any]] = {}
    grouped: dict[tuple[str, str], list[tuple[float | None, bool]]] = defaultdict(list)
    gaps = {"missing_phase": 0, "missing_outcome": 0, "missing_call_id": 0}
    for event in events:
        payload = json.loads(event["payload"])
        call_id = payload.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            gaps["missing_call_id"] += 1
            continue
        key = (event["session_id"], call_id)
        phase = payload.get("phase")
        if not isinstance(phase, str) or not phase:
            gaps["missing_phase"] += 1
        if event["kind"] == "tool_intent":
            if (
                cutoff
                and (when := parse_timestamp(event["created_at"]))
                and when < cutoff
            ):
                continue
            pending[key] = {
                "role": sessions.get(event["session_id"], "unknown"),
                "tool": payload.get("tool") or "unknown",
                "started": parse_timestamp(event["created_at"]),
            }
            continue
        intent = pending.pop(key, None)
        if intent is None:
            continue
        failed = phase == "failed"
        if phase not in {"completed", "failed", "canceled"}:
            gaps["missing_outcome"] += 1
        finished = parse_timestamp(event["created_at"])
        started = intent["started"]
        elapsed = (
            (finished - started).total_seconds() * 1000
            if finished is not None and started is not None and finished >= started
            else None
        )
        grouped[(intent["role"], intent["tool"])].append((elapsed, failed))
    gaps["missing_outcome"] += len(pending)

    rows = []
    for (role, tool), calls in sorted(grouped.items()):
        durations = sorted(duration for duration, _ in calls if duration is not None)
        rows.append(
            {
                "role": role,
                "tool": tool,
                "calls": len(calls),
                "failures": sum(failed for _, failed in calls),
                "p50_ms": median(durations) if durations else None,
            }
        )
    return {"rows": rows, "provider_gaps": gaps}


def append_failures(report: dict[str, Any], since: str | None = None) -> int:
    from . import friction_repository
    from .store import write as store_write
    from .store.types import FrictionAddMode, FrictionAddRequest

    failures = [row for row in report["rows"] if row["failures"]]
    if not failures:
        return 0
    repository = friction_repository.open_repository()
    existing = repository.list_items(
        status="open",
        source=SOURCE,
        repo_root=None,
        global_=False,
        tag=None,
        text=None,
        offset=0,
        limit=1000,
    ).items
    by_title = {item.title: item for item in existing}
    if since:
        cutoff_date = (datetime.now(UTC) - parse_window(since)).date()
        window_start = datetime.combine(
            cutoff_date, datetime.min.time(), UTC
        ).isoformat()
    else:
        window_start = "unbounded"
    cwd = Path.cwd()
    occurrences = repository.event_log().state.occurrences
    appended = 0
    for row in failures:
        title = f"Tool failures: {row['role']} / {row['tool']}"
        item = by_title.get(title)
        mode = (
            FrictionAddMode.append(
                friction_repository.item_identifier(repository, item)
            )
            if item
            else FrictionAddMode.create(SOURCE, title, "runner tool telemetry", False)
        )
        if item:
            already_recorded = any(
                occurrence.item_event_id == item.event_id
                and (start := _WINDOW_START.search(occurrence.evidence)) is not None
                and start.group(1) == window_start
                and (count := _FAILURE_COUNT.search(occurrence.evidence)) is not None
                and int(count.group(1)) == row["failures"]
                for occurrence in occurrences
            )
            if already_recorded:
                continue
        evidence = (
            f"Observed {row['failures']} failed {row['tool']} call(s) for role "
            f"{row['role']} in the selected window. "
            f"tool-stats-window-start={window_start} "
            f"tool-stats-failures={row['failures']}"
        )
        store_write.add_friction(
            repository, FrictionAddRequest(mode, evidence, cwd, [])
        )
        appended += 1
    return appended


def _parse_options(args: list[str]) -> tuple[str | None, bool, bool]:
    by_role = friction = json_output = False
    since = None
    while args:
        arg = args.pop(0)
        if arg == "--by-role":
            by_role = True
        elif arg == "--friction":
            friction = True
        elif arg == "--json":
            json_output = True
        elif arg == "--since" and args:
            since = args.pop(0)
            parse_window(since)
        elif arg == "--since":
            raise ValueError("--since requires a duration")
        else:
            raise ValueError(f"unexpected argument '{arg}'")
    if not by_role:
        raise ValueError("tools requires --by-role")
    return since, friction, json_output


def run(argv: list[str], io: object | None = None) -> int:
    args = list(argv)
    if args and args[0] == "tools":
        args.pop(0)
    if any(arg in {"-h", "--help"} for arg in args):
        _write(io, help_text("tools"))
        return 0
    json_output = "--json" in args
    try:
        since, friction, json_output = _parse_options(args)
        report = summarize(runner_database(), since)
        if friction:
            report["friction_items_updated"] = append_failures(report, since)
        if json_output:
            _write(
                io,
                json.dumps(
                    success(report, {"since": since or "all", "truncated": False}),
                    separators=(",", ":"),
                )
                + "\n",
            )
        else:
            for row in report["rows"]:
                p50 = "n/a" if row["p50_ms"] is None else f"{row['p50_ms']:.1f} ms"
                _write(
                    io,
                    f"{row['role']} / {row['tool']}: {row['calls']} calls, "
                    f"{row['failures']} failures, p50 {p50}\n",
                )
            gaps = report["provider_gaps"]
            _write(
                io,
                "Provider gaps: "
                + ", ".join(f"{key}={value}" for key, value in gaps.items())
                + "\n",
            )
            if friction:
                _write(
                    io, f"Friction items updated: {report['friction_items_updated']}\n"
                )
    except Exception as error:  # noqa: BLE001 - CLI boundary
        _write(
            io,
            json.dumps(
                tool_error("tools_stats_failed", str(error)), separators=(",", ":")
            )
            + "\n"
            if json_output
            else f"error: {error}\n",
            error=True,
        )
        return 2
    return 0


def _write(io: object | None, value: str, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    (stream or getattr(sys, "stderr" if error else "stdout")).write(value)
