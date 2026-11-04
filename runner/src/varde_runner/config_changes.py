"""Append structured records for dashboard-managed config edits."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def append_changes(path: Path, changes: dict[str, tuple[Any, Any]]) -> None:
    """Append one key/value record per changed allowlisted setting."""
    if not changes:
        return
    timestamp = datetime.now(UTC).isoformat()
    lines = [
        json.dumps(
            {"ts": timestamp, "key": key, "old": old, "new": new},
            separators=(",", ":"),
        )
        for key, (old, new) in changes.items()
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
