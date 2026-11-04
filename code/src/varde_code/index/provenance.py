"""Record and read the git HEAD and time an index was last written."""

from __future__ import annotations

import contextlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from varde_code.git import run_git

_UPSERT = (
    "INSERT INTO slice_meta(key,value) VALUES (?,?) "
    "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
)


# A non-git index has no HEAD to compare, so it is stale after this many seconds.
MAX_NON_GIT_AGE_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class Provenance:
    built_head: str
    built_at: int | None


def current_head(root: Path) -> str:
    """Return the checkout's HEAD sha, or an empty string outside git."""
    output = run_git(["rev-parse", "HEAD"], root)
    return output.strip() if output else ""


def record_built(connection: sqlite3.Connection, root: Path) -> None:
    """Write ``built_head`` and ``built_at`` through an open connection.

    The head is stored as a blob so integer affinity never rewrites a sha.
    """
    connection.execute(_UPSERT, ("built_head", current_head(root).encode()))
    connection.execute(_UPSERT, ("built_at", int(time.time())))


def read_built(db_path: str | Path) -> Provenance:
    """Read recorded provenance; missing keys give an empty head and no time."""
    try:
        with sqlite3.connect(
            f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True
        ) as db:
            rows = dict(
                db.execute(
                    "SELECT key,value FROM slice_meta "
                    "WHERE key IN ('built_head','built_at')"
                )
            )
    except sqlite3.Error:
        return Provenance("", None)
    head = rows.get("built_head", b"")
    built_at = rows.get("built_at")
    return Provenance(
        head.decode() if isinstance(head, bytes) else str(head),
        built_at if isinstance(built_at, int) else None,
    )


def non_git_age_expired(built: Provenance, head: str, now: float | None = None) -> bool:
    """Whether a non-git index is older than ``MAX_NON_GIT_AGE_SECONDS``."""
    if head or built.built_at is None:
        return False
    return (now or time.time()) - built.built_at > MAX_NON_GIT_AGE_SECONDS


def refresh_provenance_if_due(db_path: Path, root: Path) -> None:
    """Re-record provenance when HEAD moved or a non-git index aged out.

    Called after a refresh verified the content fresh; an unchanged HEAD on a
    young index writes nothing, so mtime stays stable.
    """
    head = current_head(root)
    built = read_built(db_path)
    if head == built.built_head and not non_git_age_expired(built, head):
        return
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        record_built(db, root)
        db.commit()
