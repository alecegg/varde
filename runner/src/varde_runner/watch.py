"""Snapshot and event streaming for one session.

All store access, ``wake`` calls, and watch iteration must run on the event-loop
thread because a SessionStore owns a single thread-bound SQLite connection.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from varde_runner.store import SessionStore


def snapshot(
    store: SessionStore, session_id: str, *, limit: int = 200
) -> dict[str, Any]:
    if limit < 0:
        raise ValueError("limit must not be negative")
    session = store.get_session(session_id)
    if session is None:
        raise KeyError(session_id)
    events = store.latest_events(session_id, limit) if limit else []
    last_seq = int(session["last_event_seq"])
    waits = [wait for wait in store.pending_waits() if wait["session_id"] == session_id]
    return {
        "session": session,
        "last_seq": last_seq,
        "open_intents": store.open_intents(session_id),
        "pending_waits": waits,
        "events": events,
        "truncated": store.event_count(session_id) > limit,
        "window_start": events[0]["seq"] if events else last_seq,
    }


class WatchHub:
    """Coalesced wake signals; event rows remain in the store, not in queues."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Event]] = {}

    def wake(self, session_id: str) -> None:
        for signal in tuple(self._subscribers.get(session_id, ())):
            signal.set()

    async def watch(
        self,
        store: SessionStore,
        session_id: str,
        after_seq: int | None = None,
        queue_limit: int = 256,
        page: int = 200,
    ) -> AsyncGenerator[dict[str, Any]]:
        if queue_limit < 1 or page < 1:
            raise ValueError("queue_limit and page must be positive")
        signal = asyncio.Event()
        subscribers = self._subscribers.setdefault(session_id, set())
        subscribers.add(signal)
        cursor = 0
        try:
            window_start, last_seq = store.event_cursor_bounds(session_id, 200)
            invalid_cursor = False
            if after_seq is not None:
                if last_seq is None or window_start is None:
                    invalid_cursor = after_seq > 0
                else:
                    invalid_cursor = after_seq < window_start or after_seq > last_seq
            if after_seq is None or invalid_cursor:
                current = snapshot(store, session_id)
                yield {"type": "snapshot", **current}
                cursor = current["last_seq"]
            elif after_seq is not None:
                cursor = after_seq
            while True:
                if store.event_count_after(session_id, cursor) > queue_limit:
                    current = snapshot(store, session_id)
                    yield {"type": "snapshot", **current}
                    cursor = current["last_seq"]
                    continue
                rows = store.events_after(session_id, cursor, limit=page)
                if rows:
                    for row in rows:
                        cursor = row["seq"]
                        yield {"type": "event", **row}
                    continue
                signal.clear()
                # Recheck after clearing to close the append/clear race.
                if store.events_after(session_id, cursor, limit=1):
                    continue
                await signal.wait()
        finally:
            subscribers.discard(signal)
            if not subscribers:
                self._subscribers.pop(session_id, None)
