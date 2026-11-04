"""Legacy stray message store operations for the files backend."""

from __future__ import annotations

import json
from pathlib import Path


def read_stray_messages(inbox: Path) -> tuple[list[dict[str, object]], int]:
    """Read the legacy message log from a discovered stray inbox."""
    try:
        lines = (inbox / "messages.jsonl").read_bytes().splitlines()
    except FileNotFoundError:
        return [], 0
    messages = []
    skipped = 0
    for line in lines:
        try:
            row = json.loads(line.decode("utf-8"))
        except ValueError, UnicodeDecodeError:
            skipped += 1
            continue
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            messages.append(row)
        else:
            skipped += 1
    return messages, skipped


def remove_stray_store(inbox: Path) -> None:
    """Remove a successfully migrated legacy log and its empty directories."""
    (inbox / "messages.jsonl").unlink(missing_ok=True)
    memory_bank = inbox.parents[2]
    for directory in (inbox, inbox.parent, inbox.parent.parent, memory_bank):
        try:
            directory.rmdir()
        except OSError:
            break
