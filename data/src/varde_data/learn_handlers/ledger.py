"""Ledger and digest handlers for ``varde learn store``."""

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

from varde_data.backends.files.ledger import FilesLedger
from varde_data.backends.sqlite.learn_ledger import SqliteLedger, replace_all
from varde_data.backends.sqlite.learn_schema import connect, count_rows
from varde_data.learn_store_mode import learn_db_path, read_learn_mode
from varde_data.records.ledger import Digest, LedgerRow

_ANALYZED = "analyzed.jsonl"
_DIGESTS = "digests"
_BACKUP = "learn.sqlite3.ledger-backup"


def rows(root: Path) -> int:
    """Count analyzed rows (latest per harness+session) on the active backend."""
    if read_learn_mode(root).mode("ledger") == "sqlite":
        return count_rows(root, "analyzed")
    return len(FilesLedger(root).analyzed())


def _file_digests(root: Path) -> list[Digest]:
    found: list[Digest] = []
    files = FilesLedger(root)
    for path in sorted((root / _DIGESTS).glob("*.json")):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        digest = files.read_digest(day)
        if digest is not None:
            found.append(digest)
    return found


def _source(root: Path) -> tuple[list[LedgerRow], list[Digest]]:
    return FilesLedger(root).analyzed(), _file_digests(root)


def _backup(root: Path) -> None:
    """Online-backup the imported database; the source files stay as they are."""
    target = root / _BACKUP
    temp = root / f"{_BACKUP}.tmp"
    try:
        temp.unlink(missing_ok=True)
        with (
            closing(sqlite3.connect(learn_db_path(root))) as source,
            closing(sqlite3.connect(temp)) as copy,
        ):
            source.backup(copy)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def migrate(root: Path, *, dry_run: bool) -> dict[str, Any]:
    """Import analyzed rows and digests from the files into ``learn.sqlite3``."""
    analyzed, digests = _source(root)
    counts = {"analyzed": len(analyzed), "digests": len(digests)}
    if dry_run:
        return {"ok": True, **counts}
    with closing(connect(root)) as connection:
        replace_all(connection, analyzed, digests)
    verified = verify(root)
    if verified["ok"]:
        _backup(root)
    return {**counts, **verified}


def _row_missing(source: LedgerRow, stored: dict[tuple[str, str], LedgerRow]) -> bool:
    """A source row is covered by an equal row or a later write of its key."""
    current = stored.get((source.harness, source.session))
    if current is None:
        return True
    return current != source and current.analyzed_at <= source.analyzed_at


def _digest_missing(source: Digest, stored: dict[str, Digest]) -> bool:
    """Digests are latest-wins by date: any stored digest of the date covers it."""
    return source.date not in stored


def verify(root: Path) -> dict[str, Any]:
    """Check every source row and digest is in sqlite, equal or superseded.

    Rows written to sqlite after the flip are extra and never fail the check,
    so ``retire`` is not blocked by later ledger writes.
    """
    store = SqliteLedger(root)
    analyzed, digests = _source(root)
    stored_rows = {(r.harness, r.session): r for r in store.analyzed()}
    stored_digests = {d.date: d for d in store.digests()}
    missing_rows = [r for r in analyzed if _row_missing(r, stored_rows)]
    missing_digests = [d for d in digests if _digest_missing(d, stored_digests)]
    return {
        "ok": not (missing_rows or missing_digests),
        "analyzed": {"files": len(analyzed), "sqlite": len(stored_rows)},
        "digests": {"files": len(digests), "sqlite": len(stored_digests)},
        "mismatch": [
            name
            for name, bad in (("analyzed", missing_rows), ("digests", missing_digests))
            if bad
        ],
    }


def retire(root: Path) -> dict[str, Any]:
    """Remove the source files migrate imported; the caller verified parity."""
    removed: list[str] = []
    path = root / _ANALYZED
    if path.exists():
        path.unlink()
        removed.append(_ANALYZED)
    folder = root / _DIGESTS
    for digest in _file_digests(root):
        (folder / f"{digest.date}.json").unlink()
        removed.append(f"{_DIGESTS}/{digest.date}.json")
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()
    return {"removed": removed}
