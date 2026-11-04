"""Versioned append-only ledger for daily session reviews."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import quote

LEDGER_NAME = "reviewed.jsonl"
MAX_ATTEMPTS = 3
LEDGER_VERSION = 1


def fingerprint(path: str | Path, session_id: str | None = None) -> dict[str, Any]:
    """Return a cheap content-growth fingerprint for a transcript or OpenCode DB."""
    source = Path(path)
    if _is_sqlite(source):
        return _opencode_fingerprint(source, session_id)
    stat = source.stat()
    with source.open("rb") as stream:
        lines = 0
        last_byte = b""
        while chunk := stream.read(1024 * 1024):
            lines += chunk.count(b"\n")
            last_byte = chunk[-1:]
        if stat.st_size and last_byte != b"\n":
            lines += 1
    return {"size": stat.st_size, "mtime": stat.st_mtime, "lines": lines}


def select_pending(
    inventory: Iterable[dict[str, Any]], ledger: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Select new, grown, retryable, and one-time sweep-imported sessions."""
    latest = {_key(row): row for row in ledger if _valid_key(_key(row))}
    pending = []
    for session in inventory:
        key = _key(session)
        if not _valid_key(key):
            continue
        harness, session_id = key
        prior = latest.get((harness, session_id))
        if prior is None:
            pending.append(dict(session))
            continue
        status = prior.get("status")
        if status in {"pending", "rate_limited"}:
            pending.append(dict(session))
            continue
        if status == "rate_limited":
            pending.append(dict(session))
            continue
        if status == "failed" and int(prior.get("attempts", 0)) < MAX_ATTEMPTS:
            pending.append(dict(session))
            continue
        if prior.get("status") == "analyzed" and prior.get("source") == "sweep":
            pending.append(dict(session))
            continue
        current = session.get("fingerprint")
        previous = prior.get("fingerprint")
        if (
            status in {"analyzed", "skipped"}
            and current is not None
            and _grew(current, previous)
        ):
            if status == "skipped" and str(prior.get("reason", "")).startswith(
                "ignored"
            ):
                continue
            row = dict(session)
            row["resume_position"] = int(
                prior.get("resume_position", _position(previous))
            )
            if status == "skipped":
                row["attempts"] = 0
            pending.append(row)
    return pending


def mark(
    store_dir: str | Path,
    row: dict[str, Any],
    *,
    latest_by_key: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """Append a result and update the caller's latest-row index."""
    directory = Path(store_dir)
    directory.mkdir(parents=True, exist_ok=True)
    record = dict(row)
    record.setdefault("version", LEDGER_VERSION)
    key = _key(record)
    if not _valid_key(key):
        raise ValueError("review ledger rows require a harness and session id")
    if record.get("status") == "analyzed" and not isinstance(
        record.get("fingerprint"), dict
    ):
        raise ValueError("analyzed review rows require a fingerprint")
    existing = latest_by_key.get(key)
    status = record.get("status")
    if status == "failed":
        prior_attempts = int(existing.get("attempts", 0)) if existing else 0
        grew_after_skip = (
            existing
            and existing.get("status") == "skipped"
            and isinstance(record.get("fingerprint"), dict)
            and _grew(record["fingerprint"], existing.get("fingerprint"))
        )
        if (
            existing
            and existing.get("status") == "skipped"
            and (record.get("attempts") == 0 or grew_after_skip)
        ):
            prior_attempts = 0
        attempts = prior_attempts + 1
        record["attempts"] = attempts
        if attempts >= MAX_ATTEMPTS:
            record["status"] = "skipped"
            record["last_error"] = record.get("reason")
            record["reason"] = "too large or unreadable"
    elif status == "rate_limited":
        record["attempts"] = int(existing.get("attempts", 0)) if existing else 0
    elif status == "analyzed":
        record["attempts"] = 0
    else:
        record.setdefault(
            "attempts", int(existing.get("attempts", 0)) if existing else 0
        )
    _append(directory, record)
    latest_by_key[key] = record
    return record


def import_analyzed(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert legacy analyzed rows into one-time review candidates."""
    imported = []
    for source in rows:
        harness, session_id = _key(source)
        if not _valid_key((harness, session_id)):
            continue
        imported.append(
            {
                "harness": harness,
                "session_id": session_id,
                "status": "analyzed",
                "source": "sweep",
                "attempts": 0,
                "version": LEDGER_VERSION,
            }
        )
    return imported


def write_imported(
    store_dir: str | Path, rows: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Append imported analyzed rows once, skipping keys already in the ledger."""
    directory = Path(store_dir)
    existing = set(read_index(directory))
    added = []
    for row in import_analyzed(rows):
        key = _key(row)
        if key in existing:
            continue
        _append(directory, row)
        existing.add(key)
        added.append(row)
    return added


def read_all(store_dir: str | Path) -> list[dict[str, Any]]:
    """Read latest rows per harness and session, ignoring malformed JSONL lines."""
    return list(read_index(store_dir).values())


def read_index(store_dir: str | Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Read the latest ledger row for each harness and session key."""
    path = Path(store_dir) / LEDGER_NAME
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    except OSError, UnicodeDecodeError:
        return {}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and _valid_key(_key(row)):
            latest[_key(row)] = row
    return latest


def _key(row: dict[str, Any]) -> tuple[Any, Any]:
    return row.get("harness"), row.get("session_id", row.get("session"))


def _valid_key(key: tuple[Any, Any]) -> bool:
    return all(isinstance(part, str) and part.strip() for part in key)


def _grew(current: dict[str, Any], previous: Any) -> bool:
    if not isinstance(previous, dict):
        return False
    fields = ("size", "mtime", "lines", "messages", "max_message_time")
    return any(
        current.get(field) is not None
        and previous.get(field) is not None
        and current[field] > previous[field]
        for field in fields
    )


def _position(previous: Any) -> int:
    if not isinstance(previous, dict):
        return 0
    return int(previous.get("lines", previous.get("messages", 0)))


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _opencode_fingerprint(path: Path, session_id: str | None) -> dict[str, Any]:
    uri = f"file:{quote(str(path.resolve()), safe='/:')}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(session_message)")}
        use_updated = "time_updated" in columns
        if session_id and use_updated:
            query = (
                "SELECT count(*), coalesce(max(time_updated), 0) "
                "FROM session_message WHERE session_id=?"
            )
        elif session_id:
            query = (
                "SELECT count(*), coalesce(max(time_created), 0) "
                "FROM session_message WHERE session_id=?"
            )
        elif use_updated:
            query = (
                "SELECT count(*), coalesce(max(time_updated), 0) FROM session_message"
            )
        else:
            query = (
                "SELECT count(*), coalesce(max(time_created), 0) FROM session_message"
            )
        if session_id:
            row = db.execute(
                query,
                (session_id,),
            ).fetchone()
        else:
            row = db.execute(query).fetchone()
    return {"messages": int(row[0]), "max_message_time": row[1]}


def _append(directory: Path, row: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LEDGER_NAME
    payload = (json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n").encode()
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell():
            stream.seek(-1, 2)
            if stream.read(1) != b"\n":
                payload = b"\n" + payload
        stream.seek(0, 2)
        stream.write(payload)
