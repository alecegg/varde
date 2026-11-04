"""Hook diagnostics event writer and session-start note command."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, NoReturn, cast

from varde_core.constants import TOZ_NOTE

from varde_toz.config import config_dir, env_os

VALID_HARNESSES = {"claude-code", "codex", "pi", "opencode"}
VALID_OUTCOMES = {"captured", "skipped", "failed"}


def _raise_validation(error: Exception) -> NoReturn:
    raise error


VALID_REASONS = {
    "stored",
    "invalid-payload",
    "unsupported-shape",
    "binary-media",
    "excluded",
    "pass-through",
    "spawn",
    "timeout",
    "exit",
    "empty-response",
    "invalid-response",
    "missing-update",
    "hook-error",
}
EVENT_HELP = """Record a metadata-only harness outcome

Usage: varde run event [OPTIONS] --harness <HARNESS> --outcome <OUTCOME> --reason <REASON>

Options:
      --fallback-dir <FALLBACK_DIR>  External store to try after primary-store access fails
      --harness <HARNESS>            
      --outcome <OUTCOME>            [possible values: captured, skipped, failed]
      --project <PROJECT>            Project directory (default: git root of cwd, else cwd)
      --json                         Machine-readable JSON output
      --reason <REASON>              
      --quiet                        Print only the handle line on overflow
      --tool <TOOL>                  [default: ""]
      --bytes <BYTES>                [default: 0]
  -h, --help                         Print help
"""
NOTE_HELP = """Print the session-start usage note (used by harness hooks)

Usage: varde run note [OPTIONS]

Options:
      --fallback-dir <FALLBACK_DIR>  External store to try after primary-store access fails
      --harness <HARNESS>            Emit in the hook JSON format for this harness (claude-code); plain text otherwise
      --project <PROJECT>            Project directory (default: git root of cwd, else cwd)
      --json                         Machine-readable JSON output
      --quiet                        Print only the handle line on overflow
  -h, --help                         Print help
"""


def _parse(argv: list[str]) -> tuple[dict[str, str], bool]:
    values: dict[str, str] = {}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ("-h", "--help"):
            return values, True
        if not arg.startswith("--"):
            raise ValueError(f"unexpected argument: {arg}")
        name = arg[2:]
        if "=" in name:
            key, value = name.split("=", 1)
        else:
            key = name
            if index + 1 >= len(argv):
                raise ValueError(f"argument {arg}: expected one argument")
            index += 1
            value = argv[index]
        if key not in {"harness", "outcome", "reason", "tool", "bytes"}:
            raise ValueError(f"unexpected argument: --{key}")
        values[key] = value
        index += 1
    return values, False


def main(argv: list[str]) -> int:
    if not argv:
        return 2
    command = argv[0]
    if command == "note":
        try:
            values, help_requested = _parse(argv[1:])
            if help_requested:
                print(NOTE_HELP, end="")
                return 0
            value = note_text(values.get("harness"))
            print(value)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        else:
            return 0
    if command != "event":
        return 2
    try:
        values, help_requested = _parse(argv[1:])
        if help_requested:
            print(EVENT_HELP, end="")
            return 0
        harness, outcome, reason = (
            values["harness"],
            values["outcome"],
            values["reason"],
        )
        tool, size = values.get("tool", ""), int(values.get("bytes", "0"))
        if size < 0:
            _raise_validation(ValueError("bytes must be non-negative"))
        if outcome not in VALID_OUTCOMES:
            _raise_validation(
                ValueError(f"invalid value '{outcome}' for '--outcome <OUTCOME>'")
            )
        _record(harness, outcome, reason, tool, size)
    except (KeyError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    else:
        return 0


def _record(harness: str, outcome: str, reason: str, tool: str, size: int) -> None:
    harness = harness if harness in VALID_HARNESSES else "unknown"
    outcome = outcome if outcome in VALID_OUTCOMES else "failed"
    reason = reason if reason in VALID_REASONS else "other"
    tool = "".join(c for c in tool if c.isascii() and (c.isalnum() or c in "-_."))[:64]
    event = {
        "time": int(time.time()),
        "harness": harness,
        "outcome": outcome,
        "reason": reason,
        "tool": tool,
        "bytes": size,
    }
    root = config_dir()
    try:
        _write_record(root, event)
    except OSError:
        fallback = _fallback_root()
        if fallback is None or fallback == root:
            raise
        _write_record(fallback, event)
    else:
        return


def _write_record(root: Path, event: dict[str, object]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    current, previous = root / "diagnostics.jsonl", root / "diagnostics.1.jsonl"
    lock_path = root / "diagnostics.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        with os.fdopen(lock_fd, "a") as lock:
            lock_fd = -1
            try:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            except ImportError:
                pass
            if current.exists() and current.stat().st_size >= 1024 * 1024:
                previous.unlink(missing_ok=True)
                current.replace(previous)
            log_fd = os.open(current, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            try:
                os.fchmod(log_fd, 0o600)
                with os.fdopen(log_fd, "a") as stream:
                    log_fd = -1
                    stream.write(json.dumps(event, separators=(",", ":")) + "\n")
            finally:
                if log_fd >= 0:
                    os.close(log_fd)
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)


def record_best_effort(
    harness: str, outcome: str, reason: str, tool: str, size: int
) -> None:
    with contextlib.suppress(Exception):
        _record(harness, outcome, reason, tool, size)


def _summary() -> dict[str, object] | None:
    now = int(time.time())
    counts = {"captured": 0, "skipped": 0, "failed": 0}
    unreadable_lines = 0
    unavailable_sources = 0
    failures_by_reason: dict[object, int] = {}
    last_failure: str | None = None
    last_failure_time = 0
    roots = {config_dir()}
    fallback = _fallback_root()
    if fallback is not None:
        roots.add(fallback)
    for root in roots:
        unavailable = False
        for path in (root / "diagnostics.1.jsonl", root / "diagnostics.jsonl"):
            try:
                rows = path.read_text().splitlines()
            except FileNotFoundError:
                continue
            except OSError:
                unavailable = True
                continue
            for line in rows:
                try:
                    event = json.loads(line)
                    timestamp = int(cast("Any", event["time"]))
                    outcome = event["outcome"]
                except ValueError, TypeError, KeyError:
                    unreadable_lines += 1
                    continue
                if timestamp < now - 7 * 24 * 60 * 60:
                    continue
                if outcome in ("captured", "skipped"):
                    counts[outcome] += 1
                elif outcome == "failed":
                    counts["failed"] += 1
                    reason = event.get("reason", "other")
                    failures_by_reason[reason] = failures_by_reason.get(reason, 0) + 1
                    if timestamp >= last_failure_time:
                        last_failure_time = timestamp
                        last_failure = (
                            f"{event.get('harness', 'unknown')} "
                            f"{event.get('tool', '')} {reason} at unix {timestamp}"
                        )
        if unavailable:
            unavailable_sources += 1
    return {
        **counts,
        "unreadable_lines": unreadable_lines,
        "unavailable_sources": unavailable_sources,
        "failures_by_reason": failures_by_reason,
        "last_failure": last_failure,
    }


def _fallback_root() -> Path | None:
    configured = env_os("TOZ_FALLBACK_DIR")
    if not configured:
        return None
    root = Path(configured)
    if not root.is_absolute() or ".." in root.parts:
        return None
    try:
        resolved = root.resolve()
        from varde_toz.project import project_root

        project = project_root()
        if resolved == project or project in resolved.parents:
            return None
    except OSError:
        return None
    else:
        return resolved


def note_text(harness: str | None = None) -> str:
    note = TOZ_NOTE
    try:
        summary = _summary()
        if summary and (
            summary["failed"]
            or summary["unreadable_lines"]
            or summary["unavailable_sources"]
        ):
            note += (
                f"\nToz recorded {summary['failed']} hook failure(s), "
                f"{summary['unreadable_lines']} unreadable record(s), and "
                f"{summary['unavailable_sources']} unavailable diagnostic "
                "source(s) recently. Run `varde setup doctor --json` and "
                "report recurring failures."
            )
    except OSError:
        note += "\nToz diagnostics are unavailable. Run `varde setup doctor --json`."
    if harness == "claude":
        harness = "claude-code"
    if harness in ("claude-code", "codex"):
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": note,
                }
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    return note
