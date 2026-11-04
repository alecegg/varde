"""Report recorded Varde command calls."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from varde_core.envelope import success, tool_error

from .calls import (
    RankRow,
    parse_timestamp,
    parse_window,
    rank_commands,
    read_calls_strict,
)
from .calls_retention import note_calls_used, report_meta
from .errors import StoreConfig, StoreIo
from .help import help_text


def run(argv: list[str], io: object | None = None) -> int:
    args = list(argv)
    if args and args[0] == "calls":
        args.pop(0)
    if any(token in {"-h", "--help"} for token in args):
        _write(io, help_text("calls"))
        return 0
    window: str | None = None
    json_requested = False
    try:
        while args:
            argument = args.pop(0)
            if argument == "--json":
                json_requested = True
            elif argument == "--window" and args:
                window = args.pop(0)
            elif argument == "--window":
                _invalid_argument("--window requires a duration")
            else:
                _invalid_argument(f"unexpected argument '{argument}'")
        duration = None if window is None else parse_window(window)
        rows = read_calls_strict()
        if duration is not None:
            cutoff = datetime.now(UTC) - duration
            rows = [
                row
                for row in rows
                if (when := parse_timestamp(row["ts"])) is not None and when >= cutoff
            ]
        report = rank_commands(rows)
        note_calls_used(rows)
        meta = report_meta(window or "all", duration)
        if json_requested:
            _write_json(io, success(report, meta))
        else:
            _write(io, _format(report))
    except (StoreConfig, StoreIo, ValueError) as error:
        _error(io, error, json_requested)
        return 2
    else:
        return 0


def _invalid_argument(message: str) -> None:
    raise ValueError(message)


def _format(report: dict[str, list[RankRow]]) -> str:
    lines = []
    for group, rows in report.items():
        lines.append(f"{group.title()}:")
        if not rows:
            lines.append("  No calls recorded.")
        for row in rows:
            key = row["key"] if row["key"] is not None else "unknown session"
            lines.append(
                f"  {key}: {row['calls']} calls, {row['failures']} failures "
                f"({row['failure_rate']:.0%}), {row['retries']} retries "
                f"({row['retry_rate']:.0%})"
            )
    return "\n".join(lines) + "\n"


def _write_json(io: object | None, value: object) -> None:
    _write(io, json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n")


def _error(io: object | None, error: Exception, as_json: bool) -> None:
    if as_json:
        _write(
            io,
            json.dumps(tool_error(getattr(error, "code", "usage_error"), str(error)))
            + "\n",
            True,
        )
    else:
        _write(io, f"error: {error}\n", True)


def _write(io: object | None, value: str, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    (stream or getattr(sys, "stderr" if error else "stdout")).write(value)
