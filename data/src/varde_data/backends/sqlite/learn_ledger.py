"""SQLite backend for analyzed sessions and sweep digests (``learn.sqlite3``)."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from varde_data.backends.sqlite.learn_schema import connect
from varde_data.learn_store_mode import (
    StaleGeneration,
    learn_db_path,
    writer_target,
)
from varde_data.records.ledger import Digest, LedgerRow

_FIELDS = ("summary", "metrics", "friction_added")


def row_json(row: LedgerRow) -> str:
    """Serialize a row keeping only the fields it has (absent stays absent)."""
    value: dict[str, Any] = {
        "session": row.session,
        "harness": row.harness,
        "analyzed_at": row.analyzed_at,
    }
    for field in _FIELDS:
        if getattr(row, field) is not None:
            value[field] = getattr(row, field)
    return json.dumps(value, separators=(",", ":"))


def row_from_json(text: str) -> LedgerRow:
    value = json.loads(text)
    return LedgerRow(
        value["session"],
        value["harness"],
        value["analyzed_at"],
        value.get("summary"),
        value.get("metrics"),
        value.get("friction_added"),
    )


def replace_all(
    connection: sqlite3.Connection,
    rows: list[LedgerRow],
    digests: list[Digest],
) -> None:
    """Replace the ledger tables with the given content in one transaction."""
    with connection:
        connection.execute("DELETE FROM analyzed")
        connection.execute("DELETE FROM digests")
        connection.executemany(
            "INSERT INTO analyzed(harness, session, row) VALUES (?, ?, ?)",
            [(row.harness, row.session, row_json(row)) for row in rows],
        )
        connection.executemany(
            "INSERT INTO digests(run_date, text, candidates) VALUES (?, ?, ?)",
            [(d.date, d.text, json.dumps(d.candidates)) for d in digests],
        )


class SqliteLedger:
    """Ledger rows keyed by harness+session (latest wins) and digests by date."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @contextmanager
    def _writer(self) -> Iterator[sqlite3.Connection]:
        with writer_target(self.root, "ledger") as (backend, generation):
            if backend != "sqlite":
                raise StaleGeneration(
                    f"ledger is on {backend} at generation {generation}; "
                    "reopen the store"
                )
            with closing(connect(self.root)) as connection:
                yield connection

    def mark(
        self,
        harness: str,
        session: str,
        when: str,
        summary: str,
        metrics: dict[str, Any] | None = None,
        friction_added: list[str] | None = None,
    ) -> None:
        if not (harness and session and when):
            return  # the files backend never reports such rows
        row = LedgerRow(
            session, harness, when, summary, metrics or {}, friction_added or []
        )
        with self._writer() as connection, connection:
            connection.execute(
                "INSERT INTO analyzed(harness, session, row) VALUES (?, ?, ?) "
                "ON CONFLICT(harness, session) DO UPDATE SET row = excluded.row",
                (harness, session, row_json(row)),
            )

    def analyzed(self) -> list[LedgerRow]:
        if not learn_db_path(self.root).is_file():
            return []
        with closing(connect(self.root)) as connection:
            found = connection.execute("SELECT row FROM analyzed ORDER BY rowid")
            return [row_from_json(text) for (text,) in found.fetchall()]

    def seen(self, harness: str) -> set[str]:
        return {row.session for row in self.analyzed() if row.harness == harness}

    def write_digest(
        self, run_date: date, text: str, candidates: list[dict[str, Any]]
    ) -> None:
        with self._writer() as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO digests(run_date, text, candidates) "
                "VALUES (?, ?, ?)",
                (run_date.isoformat(), text, json.dumps(candidates)),
            )

    def read_digest(self, run_date: date) -> Digest | None:
        return next((d for d in self.digests() if d.date == run_date.isoformat()), None)

    def digests(self) -> list[Digest]:
        if not learn_db_path(self.root).is_file():
            return []
        with closing(connect(self.root)) as connection:
            found = connection.execute(
                "SELECT run_date, text, candidates FROM digests ORDER BY run_date"
            )
            return [Digest(d, t, json.loads(c)) for d, t, c in found.fetchall()]
