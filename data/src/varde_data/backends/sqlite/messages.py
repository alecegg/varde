"""SQLite implementation of the message repository."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import closing, contextmanager
from pathlib import Path

from varde_core.sqlite import configure_connection
from varde_data.errors import Invalid, Locked, NotFound
from varde_data.locking import atomic_write, read_complete_lines
from varde_data.records.messages import (
    Delivery,
    DeliveryOutcome,
    Message,
    MessageStatus,
    NewMessage,
    NoteRef,
    ReaderResolver,
    ReadResult,
    RelayEvent,
)
from varde_data.repos.messages import (
    StaticReaderResolver,
    parse_messages,
    timestamp,
    validate_address,
    validate_message,
    validate_message_id,
)
from varde_data.version import Cursor, Version

SCHEMA_VERSION = 5


def _row_id(row: Message | Mapping[str, object]) -> str | None:
    if isinstance(row, Message):
        return row.id
    message_id = row.get("id")
    return message_id if isinstance(message_id, str) else None


class SQLiteMessages:
    """SQLite message repository; FULL sync uses fsync, not macOS F_FULLFSYNC."""

    def __init__(
        self,
        path: Path,
        resolver: ReaderResolver | None = None,
        *,
        busy_timeout: float = 30,
    ) -> None:
        self.path = path
        self.busy_timeout = busy_timeout
        self.resolver = resolver or StaticReaderResolver()
        with self._connection() as db:
            self._migrate(db)

    def _migrate(self, db: sqlite3.Connection) -> None:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise Invalid(f"message database version {version} is newer than supported")
        if version == SCHEMA_VERSION:
            return
        backup = self._backup_v4(db) if version == 4 else None
        try:
            self._apply_migration(db)
        except BaseException:
            db.rollback()
            if backup is not None:
                self._restore_v4(db, backup)
            raise

    def _apply_migration(self, db: sqlite3.Connection) -> None:
        db.execute("BEGIN IMMEDIATE")
        statements = (
            (
                "CREATE TABLE IF NOT EXISTS messages ("
                "id TEXT UNIQUE, legacy_id TEXT, ts TEXT NOT NULL, "
                "sender TEXT NOT NULL, "
                "recipient TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, "
                "notes TEXT, reply_to TEXT, seq INTEGER PRIMARY KEY AUTOINCREMENT)"
            ),
            (
                "CREATE TABLE IF NOT EXISTS raw_imports ("
                "id TEXT PRIMARY KEY, wire TEXT NOT NULL)"
            ),
            (
                "CREATE TABLE IF NOT EXISTS deliveries ("
                "seq INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT NOT NULL, "
                "reader TEXT NOT NULL, session TEXT NOT NULL, via TEXT NOT NULL, "
                "event TEXT NOT NULL, at TEXT NOT NULL, action_created_at TEXT, "
                "reason TEXT, details TEXT NOT NULL DEFAULT '{}')"
            ),
            (
                "CREATE TABLE IF NOT EXISTS readers ("
                "reader TEXT PRIMARY KEY, cursor INTEGER NOT NULL)"
            ),
            (
                "CREATE TABLE IF NOT EXISTS cursor_positions ("
                "reader TEXT PRIMARY KEY, position INTEGER NOT NULL)"
            ),
            (
                "CREATE TABLE IF NOT EXISTS role_holder_cursors ("
                "role_key TEXT NOT NULL, holder TEXT NOT NULL, "
                "cursor_seq INTEGER NOT NULL, PRIMARY KEY(role_key, holder))"
            ),
            "CREATE TABLE IF NOT EXISTS concluded (address TEXT PRIMARY KEY)",
            (
                "CREATE TABLE IF NOT EXISTS meta ("
                "key TEXT PRIMARY KEY, value INTEGER NOT NULL)"
            ),
            (
                "CREATE INDEX IF NOT EXISTS deliveries_message_event "
                "ON deliveries(message_id, event)"
            ),
            (
                "CREATE INDEX IF NOT EXISTS deliveries_reader_event_message "
                "ON deliveries(reader, event, message_id)"
            ),
            (
                "CREATE INDEX IF NOT EXISTS deliveries_reader_message_event "
                "ON deliveries(reader, message_id, event)"
            ),
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('version', 0)",
        )
        for statement in statements:
            db.execute(statement)
        columns = {row[1] for row in db.execute("PRAGMA table_info(messages)")}
        if "reply_to" not in columns:
            db.execute("ALTER TABLE messages ADD COLUMN reply_to TEXT")
        unread_before = self._legacy_unread(db)
        self._seed_role_holder_cursors(db)
        if unread_before != self._role_unread_pairs(db):
            db.rollback()
            raise Invalid("message migration changed the unread set")
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.commit()

    @staticmethod
    def _seed_role_holder_cursors(db: sqlite3.Connection) -> None:
        db.execute(
            "INSERT OR IGNORE INTO role_holder_cursors(role_key,holder,cursor_seq) "
            "SELECT reader,reader,cursor FROM readers"
        )

    def _backup_v4(self, db: sqlite3.Connection) -> Path:
        directory = self.path.parent / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        backup = directory / f"messages-v4-{uuid.uuid4().hex}.sqlite3"
        with closing(sqlite3.connect(backup)) as destination:
            db.backup(destination)
        from varde_data.store_mode import marker_path

        marker = marker_path(self.path.parent.parent.parent)
        if marker.is_file():
            atomic_write(Path(f"{backup}.store-mode"), marker.read_bytes(), mode=0o600)
        backups = sorted(
            directory.glob("messages-v4-*.sqlite3"),
            key=lambda path: path.stat().st_mtime_ns,
        )
        for expired in backups[:-10]:
            expired.unlink(missing_ok=True)
            Path(f"{expired}.store-mode").unlink(missing_ok=True)
        return backup

    def _restore_v4(self, db: sqlite3.Connection, backup: Path) -> None:
        with closing(sqlite3.connect(backup)) as saved:
            saved.backup(db)
        db.commit()
        from varde_data.store_mode import marker_path

        marker = marker_path(self.path.parent.parent.parent)
        marker_backup = Path(f"{backup}.store-mode")
        if marker_backup.is_file():
            atomic_write(marker, marker_backup.read_bytes(), mode=0o600)
        else:
            marker.unlink(missing_ok=True)

    @staticmethod
    def _legacy_unread(db: sqlite3.Connection) -> set[tuple[str, str]]:
        return {
            (str(row[0]), str(row[1]))
            for row in db.execute(
                "SELECT r.reader,m.id FROM readers AS r JOIN messages AS m "
                "ON m.seq>r.cursor WHERE m.recipient=r.reader AND m.id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM deliveries AS d "
                "WHERE d.message_id=m.id AND d.reader=r.reader "
                "AND d.event IN ('delivered','dropped','legacy','acked'))"
            )
        }

    @staticmethod
    def _role_unread_pairs(db: sqlite3.Connection) -> set[tuple[str, str]]:
        return {
            (str(row[0]), str(row[1]))
            for row in db.execute(
                "SELECT c.holder,m.id FROM role_holder_cursors AS c "
                "JOIN messages AS m ON m.recipient=c.role_key "
                "AND m.seq>c.cursor_seq WHERE m.id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM deliveries AS d "
                "WHERE d.message_id=m.id AND d.reader IN (c.holder,c.role_key) "
                "AND d.event IN ('delivered','dropped','legacy','acked'))"
            )
        }

    def _connect(self) -> sqlite3.Connection:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=self.busy_timeout)
        except OSError as exc:
            raise self._inbox_invalid(exc) from exc
        db.row_factory = sqlite3.Row
        configure_connection(db)
        db.execute("PRAGMA synchronous=FULL")
        db.execute(f"PRAGMA busy_timeout={max(0, int(self.busy_timeout * 1000))}")
        return db

    @staticmethod
    def _inbox_invalid(_exc: Exception) -> Invalid:
        return Invalid(
            "message inbox is not writable; grant write access to "
            ".cache/inbox (including SQLite WAL shared-memory files)"
        )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            with closing(self._connect()) as db, db:
                yield db
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" in message or "busy" in message:
                raise Locked("message database is busy; retry the operation") from exc
            if (
                "readonly" in message
                or "read-only" in message
                or "permission" in message
                or "unable to open" in message
            ):
                raise self._inbox_invalid(exc) from exc
            raise

    @staticmethod
    def _message(row: sqlite3.Row) -> Message:
        return Message(
            row["ts"],
            row["sender"],
            row["recipient"],
            row["kind"],
            row["body"],
            row["notes"],
            row["id"],
            row["legacy_id"],
            row["reply_to"],
        )

    @staticmethod
    def _delivery(row: sqlite3.Row) -> Delivery:
        return Delivery(
            row["message_id"],
            row["reader"],
            row["session"],
            row["via"],
            row["event"],
            row["at"],
            row["action_created_at"],
            row["reason"],
            json.loads(row["details"]),
        )

    def _resolve(self, name: str) -> str:
        validate_address(name, "reader")
        return self.resolver.resolve(name)

    def _skip_delivered_prefix(
        self, db: sqlite3.Connection, reader: str, cursor: int
    ) -> int:
        addresses = sorted(self.resolver.addresses(reader))
        readers = sorted({reader, *addresses})
        address_marks = ",".join("?" for _ in addresses)
        reader_marks = ",".join("?" for _ in readers)
        first = db.execute(
            "SELECT MIN(m.seq) FROM messages AS m WHERE m.recipient IN ("  # noqa: S608
            f"{address_marks}) AND NOT EXISTS ("
            "SELECT 1 FROM deliveries AS d WHERE d.reader IN ("
            + reader_marks
            + ") AND d.message_id=m.id "
            "AND d.event IN ('delivered','dropped','legacy'))",
            (*addresses, *readers),
        ).fetchone()[0]
        if first is not None:
            return max(cursor, int(first) - 1)
        head = db.execute("SELECT COALESCE(MAX(seq),0) FROM messages").fetchone()[0]
        return max(cursor, int(head))

    @staticmethod
    def _bump(db: sqlite3.Connection) -> None:
        db.execute("UPDATE meta SET value=value+1 WHERE key='version'")

    def append(self, message: NewMessage) -> Message:
        validate_message(message)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            reader = self._resolve(message.to)
            db.execute(
                "INSERT OR IGNORE INTO readers VALUES (?, ?)",
                (
                    reader,
                    db.execute("SELECT COALESCE(MAX(seq),0) FROM messages").fetchone()[
                        0
                    ],
                ),
            )
            for _ in range(8):
                stored = Message(
                    message.ts or timestamp(),
                    message.from_,
                    message.to,
                    message.kind,
                    message.text,
                    message.notes,
                    "m-" + uuid.uuid4().hex[:8],
                    None,
                    message.reply_to,
                )
                try:
                    db.execute(
                        "INSERT INTO messages(id,legacy_id,ts,sender,recipient,kind,"
                        "body,notes,reply_to) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            stored.id,
                            None,
                            stored.ts,
                            stored.from_,
                            stored.to,
                            stored.kind,
                            stored.text,
                            stored.notes,
                            stored.reply_to,
                        ),
                    )
                    break
                except sqlite3.IntegrityError as exc:
                    if "messages.id" not in str(exc):
                        raise
            else:
                raise Invalid("could not allocate a unique message id")
            self._bump(db)
            return stored

    def head(self) -> Cursor:
        with self._connection() as db:
            return Cursor(
                str(
                    db.execute("SELECT COALESCE(MAX(seq),0) FROM messages").fetchone()[
                        0
                    ]
                )
            )

    def read_since(self, cursor: Cursor) -> ReadResult:
        pos = self._position(cursor)
        with self._connection() as db:
            if (
                pos
                > db.execute("SELECT COALESCE(MAX(seq),0) FROM messages").fetchone()[0]
            ):
                raise Invalid("message cursor is outside the stream")
            rows = db.execute(
                "SELECT * FROM messages WHERE seq>? ORDER BY seq", (pos,)
            ).fetchall()
        return ReadResult(tuple(self._message(row) for row in rows))

    def read_all(self) -> ReadResult:
        return self.read_since(Cursor("0"))

    def deliveries(self) -> tuple[Delivery, ...]:
        with self._connection() as db:
            rows = db.execute("SELECT * FROM deliveries ORDER BY seq").fetchall()
        return tuple(self._delivery(row) for row in rows)

    def status_events(self) -> tuple[Mapping[str, object], ...]:
        rows = []
        inbox = self.path.parent
        for line in read_complete_lines(inbox / "events.jsonl"):
            try:
                row = json.loads(line)
            except ValueError, UnicodeDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return tuple(rows)

    def _suppressed(
        self, db: sqlite3.Connection, message_ids: Iterable[str]
    ) -> set[tuple[str, str]]:
        ids = tuple(message_ids)
        suppressed: set[tuple[str, str]] = set()
        for start in range(0, len(ids), 900):
            batch = ids[start : start + 900]
            placeholders = ",".join("?" for _ in batch)
            rows = db.execute(
                "SELECT message_id,reader FROM deliveries "  # noqa: S608
                "WHERE event IN ('delivered','dropped','legacy') "
                f"AND message_id IN ({placeholders})",
                batch,
            ).fetchall()
            resolved_readers = {
                reader: self._resolve(reader)
                for reader in {row["reader"] for row in rows}
            }
            suppressed.update(
                (resolved_readers[row["reader"]], row["message_id"]) for row in rows
            )
        return suppressed

    def pending_by_address(self) -> Mapping[str, tuple[Message, ...]]:
        with self._connection() as db:
            rows = db.execute("SELECT * FROM messages ORDER BY seq").fetchall()
            messages = tuple(self._message(row) for row in rows)
            suppressed = self._suppressed(
                db, (message.id for message in messages if message.id is not None)
            )
        grouped: dict[str, list[Message]] = {}
        for message in messages:
            if (
                message.id is not None
                and (self._resolve(message.to), message.id) not in suppressed
            ):
                grouped.setdefault(message.to, []).append(message)
        return {key: tuple(value) for key, value in grouped.items()}

    def peek_unread(self, reader: str) -> tuple[Message, ...]:
        resolved = self._resolve(reader)
        addresses = self.resolver.addresses(resolved)
        with self._connection() as db:
            row = db.execute(
                "SELECT cursor FROM readers WHERE reader=?", (resolved,)
            ).fetchone()
            start = 0 if len(addresses) > 1 or row is None else row["cursor"]
            rows = db.execute(
                "SELECT * FROM messages WHERE seq>? ORDER BY seq", (start,)
            ).fetchall()
            suppressed = self._suppressed(
                db, (row["id"] for row in rows if row["id"] is not None)
            )
        return tuple(
            m
            for row in rows
            if (m := self._message(row)).to in addresses
            and (resolved, m.id) not in suppressed
        )

    def register_reader(self, reader: str, from_start: bool) -> None:
        resolved = self._resolve(reader)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            head = db.execute("SELECT COALESCE(MAX(seq),0) FROM messages").fetchone()[0]
            initial = 0 if from_start else head
            inserted = db.execute(
                "INSERT OR IGNORE INTO readers VALUES (?,?)", (resolved, initial)
            ).rowcount
            row = db.execute(
                "SELECT cursor FROM readers WHERE reader=?", (resolved,)
            ).fetchone()
            cursor = row["cursor"]
            if from_start:
                cursor = max(cursor, self._skip_delivered_prefix(db, resolved, 0))
                if row["cursor"] < cursor:
                    db.execute(
                        "UPDATE readers SET cursor=? WHERE reader=?",
                        (cursor, resolved),
                    )
                    db.execute(
                        "INSERT INTO cursor_positions(reader,position) VALUES(?,?) "
                        "ON CONFLICT(reader) DO UPDATE SET "
                        "position=MAX(cursor_positions.position, excluded.position)",
                        (resolved, cursor),
                    )
            if inserted or row["cursor"] < cursor:
                self._bump(db)

    def message_ids(self) -> set[str]:
        with self._connection() as db:
            rows = db.execute("SELECT id FROM messages WHERE id IS NOT NULL")
            ids = {row[0] for row in rows}
            ids.update(row[0] for row in db.execute("SELECT id FROM raw_imports"))
            return ids

    def reader_position(self, reader: str) -> str | None:
        validate_address(reader, "reader")
        reader = self._resolve(reader)
        with self._connection() as db:
            row = db.execute(
                "SELECT m.id FROM readers r LEFT JOIN messages m ON m.seq=r.cursor "
                "WHERE r.reader=?",
                (reader,),
            ).fetchone()
        return None if row is None else row["id"]

    def import_reader_position(self, reader: str, message_id: str | None) -> None:
        validate_address(reader, "reader")
        reader = self._resolve(reader)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if message_id is None:
                position = 0
            else:
                row = db.execute(
                    "SELECT seq FROM messages WHERE id=?", (message_id,)
                ).fetchone()
                if row is None:
                    raise Invalid(f"message id `{message_id}` does not exist")
                position = row["seq"]
            db.execute(
                "INSERT INTO readers(reader,cursor) VALUES(?,?) "
                "ON CONFLICT(reader) DO UPDATE SET cursor=excluded.cursor",
                (reader, position),
            )
            self._bump(db)

    def import_deliveries(self, rows: Iterable[Delivery]) -> None:
        from varde_data.backends.files.messages import _delivery_identity

        incoming = tuple(rows)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = tuple(
                self._delivery(row)
                for row in db.execute("SELECT * FROM deliveries ORDER BY seq")
            )
            known = {_delivery_identity(row) for row in existing}
            inserted = 0
            for row in incoming:
                identity = _delivery_identity(row)
                if identity in known:
                    continue
                known.add(identity)
                self._insert_delivery(db, row, row.reader)
                inserted += 1
            if inserted:
                self._bump(db)

    def import_concluded(self, addresses: Iterable[str]) -> None:
        incoming = set(addresses)
        for address in incoming:
            validate_address(address)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            before = db.total_changes
            db.executemany(
                "INSERT OR IGNORE INTO concluded(address) VALUES(?)",
                ((address,) for address in sorted(incoming)),
            )
            if db.total_changes != before:
                self._bump(db)

    def import_messages(
        self, rows: Iterable[Message | Mapping[str, object]]
    ) -> tuple[Message | Mapping[str, object], ...]:
        incoming = tuple(rows)
        if any(not _row_id(row) for row in incoming):
            raise Invalid("imported messages require an id")
        inserted: list[Message | Mapping[str, object]] = []
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            known = {
                row[0]
                for row in db.execute("SELECT id FROM messages WHERE id IS NOT NULL")
            }
            known.update(row[0] for row in db.execute("SELECT id FROM raw_imports"))
            for row in incoming:
                message_id = _row_id(row)
                if message_id is None:
                    raise Invalid("imported messages require an id")
                if message_id in known:
                    continue
                known.add(message_id)
                if isinstance(row, Message):
                    message = row
                else:
                    parsed = parse_messages(
                        json.dumps(dict(row), separators=(",", ":")).encode() + b"\n"
                    )
                    message = parsed.records[0] if parsed.records else None
                    db.execute(
                        "INSERT INTO raw_imports(id,wire) VALUES(?,?)",
                        (message_id, json.dumps(dict(row), ensure_ascii=False)),
                    )
                if message is not None:
                    db.execute(
                        "INSERT OR IGNORE INTO readers(reader,cursor) VALUES(?,?)",
                        (
                            self._resolve(message.to),
                            db.execute(
                                "SELECT COALESCE(MAX(seq),0) FROM messages"
                            ).fetchone()[0],
                        ),
                    )
                    db.execute(
                        "INSERT OR IGNORE INTO messages(id,legacy_id,ts,sender,"
                        "recipient,kind,body,notes,reply_to) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            message.id,
                            message.legacy_id,
                            message.ts,
                            message.from_,
                            message.to,
                            message.kind,
                            message.text,
                            message.notes,
                            message.reply_to,
                        ),
                    )
                inserted.append(row)
            if inserted:
                self._bump(db)
        return tuple(inserted)

    def import_log(self, source: str | Path) -> tuple[Message, ...]:
        """Import a files-backend JSONL log, preserving computed legacy ids."""
        parsed = parse_messages(Path(source).read_bytes())
        imported = self.import_messages(parsed.records)
        return tuple(row for row in imported if isinstance(row, Message))

    def commit_cursor(self, reader: str, cursor: Cursor) -> None:
        resolved = self._resolve(reader)
        position = self._position(cursor)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            max_row = db.execute(
                "SELECT COALESCE(MAX(seq),0) FROM messages"
            ).fetchone()[0]
            if position > max_row:
                raise Invalid("message cursor is outside the stream")
            db.execute(
                "INSERT INTO cursor_positions(reader,position) VALUES (?,?) "
                "ON CONFLICT(reader) DO UPDATE SET "
                "position=MAX(cursor_positions.position, excluded.position)",
                (resolved, position),
            )
            self._bump(db)

    def import_cursor(self, reader: str, cursor: Cursor) -> None:
        """Set a mirrored cursor exactly, including a required rewind."""
        resolved = self._resolve(reader)
        position = self._position(cursor)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            max_row = db.execute(
                "SELECT COALESCE(MAX(seq),0) FROM messages"
            ).fetchone()[0]
            if position > max_row:
                raise Invalid("message cursor is outside the stream")
            db.execute(
                "INSERT INTO cursor_positions(reader,position) VALUES (?,?) "
                "ON CONFLICT(reader) DO UPDATE SET position=excluded.position",
                (resolved, position),
            )
            self._bump(db)

    def unread(self, reader: str) -> tuple[Message, ...]:
        resolved = self._resolve(reader)
        with self._connection() as db:
            reader_row = db.execute(
                "SELECT cursor FROM readers WHERE reader=?", (resolved,)
            ).fetchone()
            if reader_row is None:
                db.execute("BEGIN IMMEDIATE")
                reader_row = db.execute(
                    "SELECT cursor FROM readers WHERE reader=?", (resolved,)
                ).fetchone()
                if reader_row is None:
                    head = db.execute(
                        "SELECT COALESCE(MAX(seq),0) FROM messages"
                    ).fetchone()[0]
                    db.execute(
                        "INSERT INTO readers(reader,cursor) VALUES(?,?)",
                        (resolved, head),
                    )
                    self._bump(db)
                    return ()
            start = (
                0
                if len(self.resolver.addresses(resolved)) > 1
                else reader_row["cursor"]
            )
            messages = db.execute(
                "SELECT * FROM messages WHERE seq>? ORDER BY seq", (start,)
            ).fetchall()
            suppressed = self._suppressed(
                db, (row["id"] for row in messages if row["id"] is not None)
            )
            return tuple(
                message
                for row in messages
                if (message := self._message(row)).to
                in self.resolver.addresses(resolved)
                and (resolved, message.id) not in suppressed
            )

    def claim_unread(
        self, reader: str, session: str, via: str, now: str | None = None
    ) -> tuple[Message, ...]:
        return self._claim_unread(reader, session, via, now)

    def claim_unread_with_pending(
        self,
        reader: str,
        session: str,
        via: str,
        now: str | None,
        before_claim: Callable[[sqlite3.Connection], object],
    ) -> tuple[Message, ...]:
        """Claim unread rows and persist mirror lag in the same transaction."""
        return self._claim_unread(reader, session, via, now, before_claim)

    def _claim_unread(
        self,
        reader: str,
        session: str,
        via: str | None,
        now: str | None,
        before_claim: Callable[[sqlite3.Connection], object] | None = None,
    ) -> tuple[Message, ...]:
        resolved = self._resolve(reader)
        with self._connection() as db:
            if before_claim is not None:
                reader_row = db.execute(
                    "SELECT cursor FROM readers WHERE reader=?", (resolved,)
                ).fetchone()
                if reader_row is None:
                    return ()
                result = self._claim_candidates(db, resolved, reader_row["cursor"])
                if not result:
                    return ()
                db.execute("BEGIN IMMEDIATE")
                reader_row = db.execute(
                    "SELECT cursor FROM readers WHERE reader=?", (resolved,)
                ).fetchone()
                if reader_row is None:
                    result = ()
                else:
                    result = self._claim_candidates(db, resolved, reader_row["cursor"])
                    if result:
                        before_claim(db)
            else:
                reader_row = db.execute(
                    "SELECT cursor FROM readers WHERE reader=?", (resolved,)
                ).fetchone()
                if reader_row is None:
                    db.execute("BEGIN IMMEDIATE")
                    head = db.execute(
                        "SELECT COALESCE(MAX(seq),0) FROM messages"
                    ).fetchone()[0]
                    db.execute(
                        "INSERT INTO readers(reader,cursor) VALUES(?,?)",
                        (resolved, head),
                    )
                    db.execute(
                        "INSERT INTO cursor_positions(reader,position) VALUES (?,?) "
                        "ON CONFLICT(reader) DO UPDATE SET "
                        "position=MAX(cursor_positions.position, excluded.position)",
                        (resolved, head),
                    )
                    self._bump(db)
                    return ()
                result = self._claim_candidates(db, resolved, reader_row["cursor"])
                if not result:
                    return ()
                db.execute("BEGIN IMMEDIATE")
                reader_row = db.execute(
                    "SELECT cursor FROM readers WHERE reader=?", (resolved,)
                ).fetchone()
                if reader_row is None:
                    head = db.execute(
                        "SELECT COALESCE(MAX(seq),0) FROM messages"
                    ).fetchone()[0]
                    db.execute(
                        "INSERT INTO readers(reader,cursor) VALUES(?,?)",
                        (resolved, head),
                    )
                    db.execute(
                        "INSERT INTO cursor_positions(reader,position) VALUES (?,?) "
                        "ON CONFLICT(reader) DO UPDATE SET "
                        "position=MAX(cursor_positions.position, excluded.position)",
                        (resolved, head),
                    )
                    self._bump(db)
                    return ()
                result = self._claim_candidates(db, resolved, reader_row["cursor"])
            if not result:
                return ()
            at = timestamp(now)
            for message in result:
                for event in ("delivered", "acked"):
                    db.execute(
                        "INSERT INTO deliveries(message_id,reader,session,via,"
                        "event,at) VALUES(?,?,?,?,?,?)",
                        (message.id, resolved, session, via, event, at),
                    )
            head = db.execute("SELECT COALESCE(MAX(seq),0) FROM messages").fetchone()[0]
            db.execute("UPDATE readers SET cursor=? WHERE reader=?", (head, resolved))
            db.execute(
                "INSERT INTO cursor_positions(reader,position) VALUES (?,?) "
                "ON CONFLICT(reader) DO UPDATE SET "
                "position=MAX(cursor_positions.position, excluded.position)",
                (resolved, head),
            )
            self._bump(db)
            return result

    def _claim_candidates(
        self, db: sqlite3.Connection, reader: str, cursor: int
    ) -> tuple[Message, ...]:
        addresses = sorted(self.resolver.addresses(reader))
        readers = sorted({reader, *addresses})
        start = 0 if len(addresses) > 1 else cursor
        address_marks = ",".join("?" for _ in addresses)
        reader_marks = ",".join("?" for _ in readers)
        rows = db.execute(
            "SELECT m.* FROM messages AS m WHERE m.seq>? "  # noqa: S608
            f"AND m.recipient IN ({address_marks}) "
            "AND NOT EXISTS (SELECT 1 FROM deliveries AS d "
            "WHERE d.reader IN (" + reader_marks + ") "
            "AND d.message_id=m.id "
            "AND d.event IN ('delivered','dropped','legacy')) "
            "ORDER BY m.seq",
            (start, *addresses, *readers),
        ).fetchall()
        return tuple(self._message(row) for row in rows)

    def record_delivery(self, delivery: Delivery) -> DeliveryOutcome:
        return self._store_delivery(delivery)

    def record_relay_event(self, event: RelayEvent) -> DeliveryOutcome:
        resolved = self._resolve(event.reader)
        delivery = Delivery(
            event.message_id,
            event.reader,
            event.session,
            event.via,
            event.event,
            event.now,
            event.action_created_at,
            event.reason,
            event.details,
        )
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if event.event in {"pushed", "skipped-busy", "failed", "target-gone"}:
                prior = db.execute(
                    "SELECT reader,action_created_at FROM deliveries "
                    "WHERE message_id=? AND event IN "
                    "('pushed','skipped-busy','failed','target-gone')",
                    (event.message_id,),
                ).fetchall()
                if any(
                    self._resolve(row["reader"]) == resolved
                    and (
                        event.action_created_at is None
                        or row["action_created_at"] is None
                        or row["action_created_at"] >= event.action_created_at
                    )
                    for row in prior
                ):
                    return DeliveryOutcome.DUPLICATE
            if event.event != "delivered":
                outcome = self._store_delivery_in_transaction(db, delivery, resolved)
                if outcome is DeliveryOutcome.RECORDED:
                    self._bump(db)
                return outcome
            prior_delivered = db.execute(
                "SELECT reader FROM deliveries "
                "WHERE message_id=? AND event='delivered'",
                (event.message_id,),
            ).fetchall()
            if any(self._resolve(row["reader"]) == resolved for row in prior_delivered):
                return DeliveryOutcome.DUPLICATE
            self._insert_delivery(db, delivery, resolved)
            self._bump(db)
            return DeliveryOutcome.RECORDED

    def _store_delivery(self, delivery: Delivery) -> DeliveryOutcome:
        resolved = self._resolve(delivery.reader)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            outcome = self._store_delivery_in_transaction(db, delivery, resolved)
            if outcome is DeliveryOutcome.RECORDED:
                self._bump(db)
            return outcome

    def _store_delivery_in_transaction(
        self,
        db: sqlite3.Connection,
        delivery: Delivery,
        resolved: str,
    ) -> DeliveryOutcome:
        if delivery.event == "delivered":
            delivered = db.execute(
                "SELECT reader FROM deliveries "
                "WHERE message_id=? AND event='delivered'",
                (delivery.message_id,),
            ).fetchall()
            if any(self._resolve(row["reader"]) == resolved for row in delivered):
                return DeliveryOutcome.DUPLICATE
        row = db.execute(
            "SELECT recipient FROM messages WHERE id=?", (delivery.message_id,)
        ).fetchone()
        if delivery.event in {"delivered", "acked"} and (
            row is None or row["recipient"] not in self.resolver.addresses(resolved)
        ):
            return DeliveryOutcome.SKIPPED
        if delivery.event == "acked":
            validate_message_id(delivery.message_id)
            if not db.execute(
                "SELECT 1 FROM deliveries WHERE message_id=? "
                "AND event='delivered' AND reader=?",
                (delivery.message_id, resolved),
            ).fetchone():
                return DeliveryOutcome.SKIPPED
        self._insert_delivery(db, delivery, resolved)
        return DeliveryOutcome.RECORDED

    @staticmethod
    def _insert_delivery(
        db: sqlite3.Connection, delivery: Delivery, reader: str
    ) -> None:
        db.execute(
            "INSERT INTO deliveries(message_id,reader,session,via,event,"
            "at,action_created_at,reason,details) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                delivery.message_id,
                reader,
                delivery.session,
                delivery.via,
                delivery.event,
                delivery.at,
                delivery.action_created_at,
                delivery.reason,
                json.dumps(dict(delivery.details), ensure_ascii=False),
            ),
        )

    def ack(self, reader: str, message_id: str, *, now: str | None = None) -> bool:
        validate_message_id(message_id)
        resolved = self._resolve(reader)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM messages WHERE id=?", (message_id,)
            ).fetchone()
            if row is None or row["recipient"] not in self.resolver.addresses(resolved):
                raise NotFound("message does not exist for this reader")
            if db.execute(
                "SELECT 1 FROM deliveries WHERE message_id=? "
                "AND event='acked' AND reader=?",
                (message_id, resolved),
            ).fetchone():
                return False
            if not db.execute(
                "SELECT 1 FROM deliveries WHERE message_id=? "
                "AND event='delivered' AND reader=?",
                (message_id, resolved),
            ).fetchone():
                raise Invalid(
                    "message must be delivered to this reader before it can be acked"
                )
            db.execute(
                "INSERT INTO deliveries(message_id,reader,session,via,event,at) "
                "VALUES(?,?,?,'cli','acked',?)",
                (message_id, resolved, "", timestamp(now)),
            )
            self._bump(db)
            return True

    def concluded_addresses(self) -> set[str]:
        with self._connection() as db:
            result = {row[0] for row in db.execute("SELECT address FROM concluded")}
        for path in (
            self.path.parent / "state.json",
            self.path.parent / "relay" / "state.json",
        ):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except OSError, ValueError:
                continue
            addresses = (
                value.get("concluded_addresses", []) if isinstance(value, dict) else []
            )
            if isinstance(addresses, list):
                result.update(
                    address for address in addresses if isinstance(address, str)
                )
        return result

    def mark_concluded(self, address: str) -> None:
        validate_address(address)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO concluded VALUES (?)", (address,))
            self._bump(db)

    def status(self) -> MessageStatus:
        with self._connection() as db:
            below_watermark_ids = {
                row[0]
                for row in db.execute(
                    "SELECT m.id FROM messages m "
                    "JOIN readers r ON r.reader=m.recipient "
                    "WHERE r.cursor>0 AND m.seq<=r.cursor AND m.id IS NOT NULL"
                )
            }
        return MessageStatus(
            sum(map(len, self.pending_by_address().values())),
            tuple(
                sorted({d.message_id for d in self.deliveries() if d.event == "acked"})
            ),
            {"below_watermark": below_watermark_ids},
        )

    def version(self) -> Version:
        with self._connection() as db:
            return Version(
                db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0]
            )

    def read_meta(self, key: str) -> str | None:
        """Read a text value from the message database metadata table."""
        with self._connection() as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def write_meta(self, key: str, value: str) -> None:
        """Atomically upsert a text value in the message database metadata."""
        with self._connection() as db:
            db.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def read_note(self, ref: NoteRef) -> str:
        try:
            return Path(str(ref)).read_text(encoding="utf-8")
        except OSError:
            raise NotFound(f"message note {ref!r} not found") from None

    @staticmethod
    def _position(cursor: Cursor) -> int:
        try:
            position = int(cursor.value)
        except ValueError:
            raise Invalid("invalid message cursor") from None
        if position < 0:
            raise Invalid("message cursor is outside the stream")
        return position


def messages_db_path(working: Path) -> Path:
    return working / ".cache" / "inbox" / "messages.sqlite3"


def message_store_files(working: Path) -> tuple[Path, ...]:
    path = messages_db_path(working)
    return (path, Path(f"{path}-wal"), Path(f"{path}-shm"))


def factory(
    working: Path,
    resolver: ReaderResolver | None = None,
    *,
    busy_timeout: float = 30,
) -> SQLiteMessages:
    return SQLiteMessages(
        messages_db_path(working), resolver, busy_timeout=busy_timeout
    )
