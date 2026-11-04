"""SQLite friction repository: the event log in ``learn.sqlite3``.

Each ``friction_events`` row holds one ``friction.jsonl`` line (without its
newline), so ``friction_events.replay`` and the event-order numeric IDs behave
exactly as they do on the files backend. Torn tails cannot occur: a row is
committed whole or not at all.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import replace
from typing import Any

from varde_data.backends.sqlite.learn_schema import connect
from varde_data.friction_events import (
    _body_dict,
    _redact_strings,
    event_to_dict,
    fold,
    replay,
    validate_event,
)
from varde_data.learn_store_mode import StaleGeneration, writer_target
from varde_data.records.friction import Event, FrictionEventLog, LogItem, LogReplay
from varde_data.repos.friction import FrictionImportEntry, FrictionImportResult
from varde_data.testing import MemoryFriction
from varde_data.version import Version

MAP_KEY = "log_map"
_STATE_QUERY = "SELECT COUNT(*), COALESCE(MAX(seq), 0) FROM friction_events"
_ROWS_QUERY = "SELECT event FROM friction_events ORDER BY seq"
Mapping = dict[str, dict[str, Any]]


def serialize_events(
    events: Iterable[Event], redact: Callable[[str], Any]
) -> list[str]:
    """Validate and redact events into the JSONL lines the files backend writes."""
    lines: list[str] = []
    for event in events:
        validate_event(event)
        body, count = _redact_strings(_body_dict(event.body), redact)
        persisted = event_to_dict(event)
        persisted["body"] = body
        redacted = event.redacted + count
        if redacted:
            persisted["redacted"] = redacted
        lines.append(json.dumps(persisted, ensure_ascii=False, separators=(",", ":")))
    return lines


def replay_rows(rows: Iterable[str]) -> LogReplay:
    """Replay stored event rows as a complete log."""
    return replay(row + "\n" for row in rows)


def read_event_rows(db: sqlite3.Connection) -> list[str]:
    return [row[0] for row in db.execute(_ROWS_QUERY)]


def insert_event_rows(db: sqlite3.Connection, rows: Iterable[str]) -> None:
    db.executemany(
        "INSERT INTO friction_events(event) VALUES (?)", ((row,) for row in rows)
    )


def read_mapping(db: sqlite3.Connection) -> Mapping:
    """Return the legacy ID and slug map kept in ``meta`` (empty when absent)."""
    row = db.execute("SELECT value FROM meta WHERE key = ?", (MAP_KEY,)).fetchone()
    if row is None:
        return {}
    try:
        value = json.loads(row[0])
    except TypeError, ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def write_mapping(db: sqlite3.Connection, mapping: Mapping) -> None:
    """Merge ``mapping`` into the stored map, section by section."""
    merged = read_mapping(db)
    for section, values in mapping.items():
        merged.setdefault(section, {}).update(values)
    db.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (MAP_KEY, json.dumps(merged, sort_keys=True, separators=(",", ":"))),
    )


@contextmanager
def write_transaction(db: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Take the database write lock for one commit-or-rollback unit."""
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.rollback()
        raise
    db.commit()


class SqliteLearnFriction(MemoryFriction):
    """Friction repository over ``friction_events`` in ``learn.sqlite3``."""

    def __init__(
        self,
        root,
        *,
        redactor: Callable[[str], tuple[str, int]] | None = None,
    ) -> None:
        super().__init__(root, redactor=redactor)
        self._cached: tuple[tuple[int, int], LogReplay] | None = None

    def _load(self) -> tuple[LogReplay, Mapping]:
        with closing(connect(self.root)) as db:
            key = tuple(db.execute(_STATE_QUERY).fetchone())
            mapping = read_mapping(db)
            if self._cached is None or self._cached[0] != key:
                self._cached = (key, replay_rows(read_event_rows(db)))
        return self._cached[1], mapping

    def _events(self) -> list[Event]:
        return self._load()[0].events

    def _state(self):
        loaded, mapping = self._load()
        state = fold(loaded.events)
        slugs = mapping.get("item_slugs", {})
        return replace(
            state,
            items=[
                replace(
                    item,
                    slug=str(
                        self._imported_slugs.get(
                            item.event_id, slugs.get(item.event_id, item.slug)
                        )
                    ),
                )
                for item in state.items
            ],
        )

    def _item(self, identifier: str | int) -> tuple[int, LogItem]:
        if isinstance(identifier, int) or str(identifier).isdecimal():
            requested_id = int(identifier)
            item_ids = self._load()[1].get("items", {})
            for index, item in enumerate(self._state().items):
                if int(item_ids.get(item.event_id, -1)) == requested_id:
                    return index, item
        return super()._item(identifier)

    def version(self) -> Version:
        with closing(connect(self.root)) as db:
            return Version(tuple(db.execute(_STATE_QUERY).fetchone()))

    def event_log(self) -> FrictionEventLog:
        replayed = self._load()[0]
        state = fold(replayed.events)
        grouped: dict[str, list] = {}
        for occurrence in state.occurrences:
            grouped.setdefault(occurrence.item_event_id, []).append(occurrence)
        return FrictionEventLog(
            tuple(replayed.events),
            replayed.lines,
            "",
            state,
            {key: tuple(value) for key, value in grouped.items()},
        )

    @contextmanager
    def _writer(self) -> Iterator[None]:
        with writer_target(self.root, "friction") as (backend, generation):
            if backend != "sqlite":
                raise StaleGeneration(
                    f"friction is on {backend} at generation {generation}; "
                    "reopen the store"
                )
            yield

    def append_event(self, event: Event) -> Event:
        return self.append_events([event])[0]

    def append_events(self, events: Iterable[Event]) -> list[Event]:
        batch = list(events)
        lines = serialize_events(batch, self._redactor)
        if not lines:
            return []
        with (
            self._lock,
            self._writer(),
            closing(connect(self.root)) as db,
            write_transaction(db),
        ):
            insert_event_rows(db, lines)
        return batch

    def _append_checked(
        self, prepare: Callable[[list[Event]], Iterable[Event]]
    ) -> list[Event]:
        with (
            self._lock,
            self._writer(),
            closing(connect(self.root)) as db,
            write_transaction(db),
        ):
            existing = replay_rows(read_event_rows(db)).events
            additions = list(prepare(existing))
            insert_event_rows(db, serialize_events(additions, self._redactor))
        return additions

    def import_entries(
        self, entries: Iterable[FrictionImportEntry], *, dry_run: bool = False
    ) -> FrictionImportResult:
        result = super().import_entries(entries, dry_run=dry_run)
        if result.id_map:
            with (
                self._writer(),
                closing(connect(self.root)) as db,
                write_transaction(db),
            ):
                write_mapping(db, result.id_map)
        return result
