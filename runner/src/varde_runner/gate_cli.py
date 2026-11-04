"""Read-only CLI for native-cutover gate evidence."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from varde_runner.gate_check import check_gate


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="varde-runner gate")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="check native cutover evidence")
    check.add_argument("--restart-at", required=True, type=_timestamp)
    check.add_argument("--since", type=_timestamp)
    check.add_argument("--until", type=_timestamp)
    check.add_argument("--json", action="store_true", required=True)
    return parser


def _read_store(database: Path):
    if not database.is_file():
        raise FileNotFoundError(f"runner store not found: {database}")
    uri = f"{database.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        sessions = [
            dict(row)
            for row in db.execute(
                "SELECT id, backend, ref, status, created_at FROM sessions"
            )
        ]
        events = [
            dict(row)
            for row in db.execute(
                "SELECT session_id, kind, created_at FROM events "
                "WHERE kind IN ('resume', 'parked')"
            )
        ]
        bindings = [
            dict(row)
            for row in db.execute("SELECT session_id FROM session_address_bindings")
        ]
    return sessions, events, bindings


def run(args: argparse.Namespace, working_dir: Path) -> int:
    database = working_dir / ".cache" / "dashboard" / "runner.sqlite3"
    try:
        sessions, events, bindings = _read_store(database)
        result = check_gate(
            sessions,
            events,
            bindings,
            args.restart_at,
            since=args.since,
            until=args.until,
        )
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"gate check failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["verdict_inputs_ok"] else 1


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "check":
        parser.error("unknown gate command")
    working = os.environ.get("VARDE_WORKING_DIR")
    if not working:
        print(
            "VARDE_WORKING_DIR must point to a Varde working directory", file=sys.stderr
        )
        return 2
    return run(args, Path(working))
