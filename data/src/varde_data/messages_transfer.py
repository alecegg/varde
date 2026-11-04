"""Append-only transfer and parity checks for message stores."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_data.backends.files.messages import FilesMessages
from varde_data.backends.files.slots_reader import SlotReader
from varde_data.backends.sqlite.messages import SQLiteMessages, messages_db_path
from varde_data.errors import Invalid
from varde_data.locking import atomic_write, file_lock, read_complete_lines
from varde_data.records.messages import Delivery
from varde_data.store_mode import (
    StoreModeInvalid,
    mark_import_verified,
    marker_path,
    parse_store_mode_record,
)

_MODE_LOCK = ".cache/inbox/store-mode.lock"


@dataclass(frozen=True)
class TransferReport:
    source_messages: int
    target_messages: int
    skipped: int
    mismatches: tuple[str, ...]
    torn_tail: int = 0

    @property
    def ok(self) -> bool:
        return not self.mismatches


def _repository(working: Path, backend: str, *, create: bool = True):
    resolver = SlotReader(working)
    if backend == "files":
        # Transfer is the explicit migration path, including rollback top-ups.
        return FilesMessages.from_store_mode(working, resolver, None)
    if backend != "sqlite":
        raise Invalid("store must be files or sqlite")
    path = messages_db_path(working)
    if not create and not path.is_file():
        return None
    return SQLiteMessages(path, resolver)


def _repo_ids(repo: Any) -> set[str]:
    return repo.message_ids() | {
        row.id for row in repo.read_all().records if row.id is not None
    }


def _message_sequences(repo: Any, working: Path) -> tuple[tuple[str, int], ...]:
    if isinstance(repo, FilesMessages):
        ordered = []
        for message in repo.read_all().records:
            if message.id is not None:
                ordered.append((message.id, len(ordered) + 1))
        return tuple(ordered)
    with closing(
        sqlite3.connect(f"{messages_db_path(working).as_uri()}?mode=ro", uri=True)
    ) as db:
        return tuple(
            (str(message_id), int(seq))
            for message_id, seq in db.execute(
                "SELECT id,seq FROM messages WHERE id IS NOT NULL ORDER BY seq"
            )
        )


def _message_replies(repo: Any) -> dict[str, str | None]:
    return {
        message.id: message.reply_to
        for message in repo.read_all().records
        if message.id is not None
    }


def _reader_names(repo: Any, working: Path) -> set[str]:
    names: set[str] = set()
    if isinstance(repo, FilesMessages):
        inbox = repo.inbox
        for folder in (inbox / "index", inbox / "cursors"):
            if folder.is_dir():
                names.update(
                    path.stem
                    if path.suffix == ".json"
                    and not path.name.endswith(".delivered.json")
                    else path.name
                    for path in folder.iterdir()
                    if path.is_file() and not path.name.endswith(".delivered.json")
                )
    else:
        db_path = messages_db_path(working)
        with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as db:
            names.update(row[0] for row in db.execute("SELECT reader FROM readers"))
    names.update(row.reader for row in _all_deliveries(repo, working))
    names.update(message.to for message in repo.read_all().records)
    return names


def _reader_positions(repo: Any, working: Path) -> dict[str, str | None]:
    return {
        reader: repo.reader_position(reader) for reader in _reader_names(repo, working)
    }


def _torn_tail(repo: Any) -> int:
    if not isinstance(repo, FilesMessages):
        return 0
    tails = 0
    for name in ("messages.jsonl", "deliveries.jsonl"):
        try:
            data = (repo.inbox / name).read_bytes()
        except FileNotFoundError:
            continue
        tails += int(bool(data) and not data.endswith(b"\n"))
    return tails


def _delivery_key(row: Delivery) -> str:
    return json.dumps(
        {
            "message_id": row.message_id,
            "reader": row.reader,
            "session": row.session,
            "via": row.via,
            "event": row.event,
            "at": row.at,
            "action_created_at": row.action_created_at,
            "reason": row.reason,
            "details": dict(row.details),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _concluded(repo: Any, working: Path) -> set[str]:
    if isinstance(repo, FilesMessages):
        return repo.concluded_addresses()
    path = messages_db_path(working)
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        return {row[0] for row in db.execute("SELECT address FROM concluded")}


def _sqlite_delivery_rows(path: Path) -> tuple[Delivery, ...]:
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        rows = db.execute("SELECT * FROM deliveries ORDER BY seq").fetchall()
    return tuple(
        Delivery(
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
            row[8],
            json.loads(row[9]),
        )
        for row in rows
    )


def _all_deliveries(repo: Any, working: Path) -> tuple[Delivery, ...]:
    if isinstance(repo, FilesMessages):
        rows: list[Delivery] = []
        known_fields = {
            "message_id",
            "reader",
            "session",
            "via",
            "event",
            "at",
            "action_created_at",
            "reason",
        }
        for line in read_complete_lines(repo.inbox / "deliveries.jsonl"):
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    continue
                rows.append(
                    Delivery(
                        raw["message_id"],
                        raw["reader"],
                        raw.get("session", ""),
                        raw.get("via", "cli"),
                        raw["event"],
                        raw["at"],
                        raw.get("action_created_at"),
                        raw.get("reason"),
                        {
                            key: value
                            for key, value in raw.items()
                            if key not in known_fields and isinstance(value, str)
                        },
                    )
                )
            except ValueError, TypeError, KeyError:
                continue
        return tuple(rows)
    return _sqlite_delivery_rows(messages_db_path(working))


def _advance_position(source: Any, target: Any, reader: str) -> None:
    source_position = source.reader_position(reader)
    target_position = target.reader_position(reader)
    if source_position is None:
        if target_position is None:
            target.import_reader_position(reader, None)
        return
    ids = tuple(message.id for message in target.read_all().records)
    order = {message_id: index for index, message_id in enumerate(ids)}
    if target_position is not None and order.get(target_position, -1) >= order.get(
        source_position, -1
    ):
        return
    target.import_reader_position(reader, source_position)


def _replay(source: Any, target: Any, working: Path) -> tuple[int, int]:
    # Copy messages first so replayed deliveries reference known ids.
    target_positions_before = _reader_positions(target, working)
    target_was_empty = not _repo_ids(target)
    read = source.read_all()
    target.import_messages(read.records)
    source_positions = _reader_positions(source, working)
    for reader in sorted(source_positions):
        if target_was_empty or reader not in target_positions_before:
            target.import_reader_position(reader, source_positions[reader])
        else:
            _advance_position(source, target, reader)
    delivery_rows = _all_deliveries(source, working)
    invalid_deliveries = 0
    if isinstance(source, FilesMessages):
        delivery_path = source.inbox / "deliveries.jsonl"
        complete_lines = read_complete_lines(delivery_path)
        invalid_deliveries = max(0, len(complete_lines) - len(delivery_rows))
    target.import_deliveries(delivery_rows)
    target.import_concluded(_concluded(source, working))
    torn = _torn_tail(source)
    return len(read.skipped) + invalid_deliveries + torn, torn


def _compare(
    source: Any, target: Any, working: Path, skipped: int = 0, torn: int = 0
) -> TransferReport:
    mismatches: list[str] = []
    source_ids, target_ids = _repo_ids(source), _repo_ids(target)
    if source_ids != target_ids:
        mismatches.append("message ids differ")
    if _message_sequences(source, working) != _message_sequences(target, working):
        mismatches.append("message sequence differs")
    if _message_replies(source) != _message_replies(target):
        mismatches.append("reply_to differs")
    source_deliveries = Counter(map(_delivery_key, _all_deliveries(source, working)))
    target_deliveries = Counter(map(_delivery_key, _all_deliveries(target, working)))
    if source_deliveries != target_deliveries:
        mismatches.append("delivery events or ack history differ")
    readers = _reader_names(source, working) | _reader_names(target, working)
    source_positions = _reader_positions(source, working)
    target_positions = _reader_positions(target, working)
    for reader in sorted(readers):
        if source_positions.get(reader) != target_positions.get(reader):
            mismatches.append(f"reader position differs for {reader}")
        source_unread = {message.id for message in source.peek_unread(reader)}
        target_unread = {message.id for message in target.peek_unread(reader)}
        if source_unread != target_unread:
            mismatches.append(f"unread set differs for {reader}")
    if _concluded(source, working) != _concluded(target, working):
        mismatches.append("concluded addresses differ")
    return TransferReport(
        len(source_ids), len(target_ids), skipped, tuple(mismatches), torn
    )


def transfer(
    working: Path, source: str, target: str, *, importing: bool = False
) -> TransferReport:
    """Append missing rows and report parity; concurrent writes may require rerun."""
    if source == target:
        raise Invalid("source and target stores must differ")
    if importing and (source, target) != ("files", "sqlite"):
        raise Invalid("import only supports --from files --to sqlite")
    src = _repository(working, source)
    dst = _repository(working, target)
    skipped, torn = _replay(src, dst, working)
    report = _compare(src, dst, working, skipped, torn)
    if importing and report.ok:
        mark_import_verified(working)
    return report


def verify(working: Path, left: str = "files", right: str = "sqlite") -> TransferReport:
    """Compare stores without creating or modifying either one."""
    if left == right:
        raise Invalid("source and target stores must differ")
    source = _repository(working, left, create=False)
    target = _repository(working, right, create=False)
    if source is None or target is None:
        existing = source or target
        count = len(existing.message_ids()) if existing is not None else 0
        missing = left if source is None else right
        return TransferReport(
            count if source else 0,
            count if target else 0,
            0,
            (f"{missing} store is absent",),
        )
    return _compare(source, target, working, torn=_torn_tail(source))


def export(working: Path, dest: Path) -> TransferReport:
    """Write a files-format copy, refusing to overwrite a live or nested inbox."""
    source_root = working.resolve()
    destination_root = dest.resolve()
    if destination_root == source_root or source_root in destination_root.parents:
        raise Invalid("export destination must be outside the live working tree")
    inbox = destination_root / ".cache" / "inbox"
    if inbox.exists() and any(inbox.iterdir()):
        raise Invalid(f"export destination is not empty: {inbox}")
    src = _repository(working, "sqlite", create=False)
    if src is None:
        raise Invalid("SQLite store is absent")
    dst = FilesMessages.from_store_mode(
        destination_root, SlotReader(destination_root), None
    )
    skipped, torn = _replay(src, dst, working)
    return _compare(src, dst, working, skipped, torn)


def repair_mode(working: Path, *, force_adopt: bool = False) -> str:
    """Repair one interrupted mode write while excluding concurrent flips."""
    path = marker_path(working)
    db_path = messages_db_path(working)
    with file_lock(working / _MODE_LOCK, timeout=2):
        marker_record = (
            parse_store_mode_record(path.read_text(encoding="utf-8"))
            if path.exists()
            else None
        )
        if not db_path.is_file():
            raise StoreModeInvalid("SQLite metadata is absent; refusing to create it")
        with closing(sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)) as db:
            row = db.execute("SELECT value FROM meta WHERE key='store_mode'").fetchone()
        db_record = parse_store_mode_record(str(row[0])) if row else None
        if marker_record == db_record and marker_record is not None:
            return "store mode already consistent"
        if marker_record is None and db_record is not None:
            if db_record.primary == "files" and db_record.mirror == "none":
                atomic_write(path, (db_record.to_json() + "\n").encode(), mode=0o600)
                return "adopted default files mode marker"
            if not force_adopt:
                raise StoreModeInvalid(
                    "database contains a nondefault mode without a marker; "
                    "rerun varde msg store verify --repair-mode --force-adopt "
                    "only after verifying the intended mode"
                )
            atomic_write(path, (db_record.to_json() + "\n").encode(), mode=0o600)
            return "force-adopted database store mode marker"
        if marker_record is None or db_record is None:
            raise StoreModeInvalid("store mode state is incomplete; refusing repair")
        if marker_record.generation == db_record.generation:
            raise StoreModeInvalid("store mode records conflict at the same generation")
        newer, older = (
            (marker_record, db_record)
            if marker_record.generation > db_record.generation
            else (db_record, marker_record)
        )
        if older.generation + 1 != newer.generation:
            raise StoreModeInvalid("store mode generations are not adjacent")
        if newer is db_record:
            atomic_write(path, (newer.to_json() + "\n").encode(), mode=0o600)
            return "completed interrupted database-first mode write"
        atomic_write(path, (db_record.to_json() + "\n").encode(), mode=0o600)
        return "rolled back marker to the matching database generation"
