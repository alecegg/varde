#!/usr/bin/env python3
"""Reject measurement results that predate the agreed measurement window."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CUTOFF = date(2026, 10, 19)
START_FIELDS = ("run_started_at", "started_at", "run_start", "start_time")


def approved_paths() -> set[str]:
    agreements = ROOT / "dev/scripts/window-agreements.md"
    return {
        line.strip()[2:].strip()
        for line in agreements.read_text().splitlines()
        if line.strip().startswith("- ") and line.strip()[2:].strip()
    }


def result_start(data: object) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in START_FIELDS:
        value = data.get(key)
        if isinstance(value, str):
            return value
    return None


def predates_window(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed_date = date.fromisoformat(value)
    else:
        parsed_date = parsed.date()
    return parsed_date < CUTOFF


def main() -> int:
    results = sorted(ROOT.glob("**/results/*.json"))
    if not results:
        print("No results JSON files found.")
        return 0

    approved = approved_paths()
    failures = []
    for path in results:
        relative = path.relative_to(ROOT).as_posix()
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"{relative}: cannot read JSON: {error}")
            continue
        started = result_start(data)
        if started is None:
            continue
        try:
            is_early = predates_window(started)
        except ValueError:
            failures.append(f"{relative}: invalid run start {started!r}")
            continue
        if is_early and relative not in approved:
            failures.append(f"{relative}: run start {started} predates {CUTOFF}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(
        f"Checked {len(results)} results JSON file(s); no unapproved pre-window runs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
