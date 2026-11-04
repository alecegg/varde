"""Append and load main-agent nudge records."""

from __future__ import annotations

import fcntl
import json
from datetime import UTC, datetime
from pathlib import Path

from varde_data.repos.messages import validate_address

REASONS = ("idle-unread", "stalled", "other")


def _path(working: str | Path) -> Path:
    return Path(working) / ".cache" / "inbox" / "nudges.jsonl"


def load(working: str | Path) -> list[dict[str, str]]:
    """Load valid nudge records from the inbox log."""
    try:
        lines = _path(working).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    records = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if (
            isinstance(record, dict)
            and record.get("event") == "main-nudge"
            and isinstance(record.get("address"), str)
            and isinstance(record.get("at"), str)
            and record.get("reason") in REASONS
        ):
            records.append(record)
    return records


def append(
    working: str | Path,
    address: str,
    reason: str,
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """Record a main-agent nudge without sending a message."""
    validate_address(address, "--to")
    if reason not in REASONS:
        raise ValueError(f"unknown nudge reason `{reason}`")
    path = _path(working)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = (
        (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    )
    record = {"event": "main-nudge", "address": address, "at": stamp, "reason": reason}
    with path.open("a", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(
            json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
        )
        stream.flush()
        fcntl.flock(stream, fcntl.LOCK_UN)
    return record
