"""Read-only mail facts used by plan pulse."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from varde_data.config import load_data_config
from varde_data.open import open_data


def unread_count(inbox: Path, reader: str) -> int:
    """Count unread mail for a reader without advancing its cursor."""
    working = inbox.parent.parent
    return len(open_data(working, load_data_config()).messages.peek_unread(reader))


def mailman_status(working: str | Path, now: datetime) -> str:
    """Return the current mailman's liveness without building a full report."""
    addresses = open_data(Path(working), load_data_config()).addresses
    current = addresses.current_token("mailman")
    if current is None:
        current = addresses.relay_snapshot().current_mailman
    if not current:
        return "none"
    return "alive" if addresses.mailman_alive(current, now) else "dead"
