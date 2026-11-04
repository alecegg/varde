"""Factory and log view for the sqlite friction contract backend."""

from __future__ import annotations

from contextlib import closing
from pathlib import Path

from varde_data.backends.sqlite.learn_friction import (
    SqliteLearnFriction,
    read_event_rows,
)
from varde_data.backends.sqlite.learn_schema import connect
from varde_data.learn_store_mode import (
    exclusive_store_lock,
    flip_domain_locked,
    read_learn_mode,
)


def factory(root: Path) -> SqliteLearnFriction:
    """Open the sqlite backend with the root's marker set to friction on sqlite."""
    if read_learn_mode(root).friction != "sqlite":
        root.mkdir(parents=True, exist_ok=True)
        with exclusive_store_lock(root):
            if read_learn_mode(root).friction != "sqlite":
                flip_domain_locked(root, "friction", "sqlite")
    return SqliteLearnFriction(root)


def read_log(root: Path) -> bytes:
    """Return the stored events as the JSONL bytes the files backend would hold."""
    if not (root / "learn.sqlite3").is_file():
        return b""
    with closing(connect(root)) as db:
        return b"".join(row.encode() + b"\n" for row in read_event_rows(db))
