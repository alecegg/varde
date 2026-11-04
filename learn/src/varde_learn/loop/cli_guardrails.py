"""List registered guardrails and record explicit firings."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from varde_core.envelope import success, tool_error

from . import calls, guardrails
from .calls_retention import note_calls_used, report_meta, window_exceeds_retention
from .errors import StoreConfig, StoreIo
from .help import help_text


class UsageError(ValueError):
    code = "usage_error"


def run(argv: list[str], io: object | None = None) -> int:
    args = list(argv)
    if args and args[0] == "guardrails":
        args.pop(0)
    if args and args[0] != "fire" and any(token in {"-h", "--help"} for token in args):
        _write(io, help_text("guardrails"))
        return 0
    json_requested = "--json" in args
    try:
        if args and args[0] == "fire":
            if any(token in {"-h", "--help"} for token in args[1:]):
                _write(io, help_text("guardrails fire"))
                return 0
            return _fire(args[1:], io)
        return _list(args, io)
    except (StoreConfig, StoreIo, ValueError) as error:
        if json_requested:
            _write(
                io,
                json.dumps(
                    tool_error(getattr(error, "code", "store_error"), str(error))
                )
                + "\n",
                True,
            )
        else:
            _write(io, f"error: {error}\n", True)
        return 2


def _list(args: list[str], io: object | None) -> int:
    dead_only = False
    json_requested = False
    window = "30d"
    while args:
        argument = args.pop(0)
        if argument == "--dead":
            dead_only = True
        elif argument == "--json":
            json_requested = True
        elif argument == "--window" and args:
            window = args.pop(0)
        elif argument == "--window":
            raise UsageError("--window requires a duration")
        else:
            raise UsageError(f"unexpected argument '{argument}'")
    try:
        duration = calls.parse_window(window)
    except ValueError as error:
        raise UsageError(str(error)) from error
    if dead_only and (days := window_exceeds_retention(duration)) is not None:
        raise UsageError(
            f"--dead needs the full window, but {window} is longer than the "
            f"{days}-day calls retention (calls_days in sweep.toml)"
        )
    entries = guardrails.load_registry()
    rows = calls.read_calls_strict()
    now = datetime.now(UTC)
    cutoff = now - duration
    filtered = [
        row
        for row in rows
        if (when := calls.parse_timestamp(row["ts"])) is not None and when >= cutoff
    ]
    counts = guardrails.firings(entries, filtered)
    dead_ids = guardrails.dead(entries, rows, duration, now)
    note_calls_used(filtered)
    meta = report_meta(window, duration)
    result = [entry for entry in entries if not dead_only or entry["id"] in dead_ids]
    data = [{**entry, **counts[entry["id"]]} for entry in result]
    if json_requested:
        _write(
            io,
            json.dumps(
                success({"guardrails": data}, meta),
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
        )
    elif not data:
        _write(io, "No guardrails found.\n")
    else:
        _write(
            io,
            "".join(
                f"{entry['id']} [{entry['kind']}] {entry['fired']} fired, "
                f"{entry['blocked']} blocked: {entry['purpose']}\n"
                for entry in data
            ),
        )
    return 0


def _fire(args: list[str], io: object | None) -> int:
    if not args or args[0].startswith("-"):
        raise UsageError("fire requires a guardrail id")
    identifier = args.pop(0)
    blocked = False
    while args:
        argument = args.pop(0)
        if argument == "--blocked":
            blocked = True
        else:
            raise UsageError(f"unexpected argument '{argument}'")
    entries = guardrails.load_registry()
    if identifier not in {entry["id"] for entry in entries}:
        raise UsageError(f"unknown guardrail id `{identifier}`")
    row: calls.CallRow = {
        "ts": datetime.now(UTC).isoformat(),
        "command": f"guardrails fire {identifier}",
        "status": calls.BLOCKED if blocked else calls.SUCCESS,
        "duration_s": 0.0,
        "session": calls.session_id(),
        "guardrail": identifier,
    }
    if not calls.append_call(row):
        _write(io, f"warning: could not record guardrail firing {identifier}\n", True)
        return 0
    _write(io, f"Recorded guardrail firing {identifier}.\n")
    return 0


def _write(io: object | None, value: str, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    (stream or getattr(sys, "stderr" if error else "stdout")).write(value)
