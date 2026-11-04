"""Compatibility adapters for relay wake and send-liveness writes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from varde_data.addresses import open_addresses


def touch_wake(working: Path) -> None:
    open_addresses(working, "files").touch_wake()


def record_send_liveness(
    working: Path, message_id: str, recipient: str, now: datetime
) -> None:
    open_addresses(working, "files").record_send_liveness(message_id, recipient, now)
