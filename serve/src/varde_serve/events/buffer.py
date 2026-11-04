"""Event envelope and the bounded replay buffer. Pure: no clock beyond `ts`."""

from __future__ import annotations

import secrets
import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

CAPACITY = 200


def parse_cursor(cursor: str | None) -> tuple[str, int] | None:
    """Split a `<gen>:<n>` cursor; None when absent or malformed."""
    gen, sep, number = (cursor or "").rpartition(":")
    if not sep or not gen or not number.isdigit():
        return None
    return gen, int(number)


def _number(event_id: str) -> int:
    return int(event_id.rpartition(":")[2])


class EventBuffer:
    """The last `capacity` events of one daemon run, ids `<gen>:<n>`."""

    def __init__(self, capacity: int = CAPACITY, gen: str | None = None) -> None:
        self.gen = gen or secrets.token_hex(4)
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._next = 1
        self._lock = threading.Lock()

    @property
    def cursor(self) -> str:
        """Id of the newest event; `<gen>:0` before any event."""
        with self._lock:
            return f"{self.gen}:{self._next - 1}"

    def publish(self, kind: str, subject: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            event = {
                "id": f"{self.gen}:{self._next}",
                "kind": kind,
                "ts": datetime.now(UTC).isoformat(),
                "subject": subject,
                "data": data,
            }
            self._next += 1
            self._events.append(event)
            return event

    def reset_frame(self) -> dict[str, Any]:
        return {
            "id": self.cursor,
            "kind": "reset",
            "ts": datetime.now(UTC).isoformat(),
            "subject": "",
            "data": {},
        }

    def since(self, cursor: str | None, limit: int = CAPACITY) -> tuple[list, bool]:
        """Return (events after `cursor`, reset).

        No cursor means "from now": nothing replayed, no reset. A cursor from
        another run, or older than the buffer, sets reset and replays nothing:
        the client must re-read state.
        """
        if cursor is None:
            return [], False
        parsed = parse_cursor(cursor)
        with self._lock:
            newest = self._next - 1
            oldest = self._events[0]["id"] if self._events else None
            floor = _number(oldest) if oldest else self._next
            if parsed is None or parsed[0] != self.gen or parsed[1] > newest:
                return [], True
            if parsed[1] < floor - 1:
                return [], True
            fresh = [e for e in self._events if _number(e["id"]) > parsed[1]]
            return fresh[:limit], False
