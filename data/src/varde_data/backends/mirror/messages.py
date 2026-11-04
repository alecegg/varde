"""Ordered, best-effort mirroring for message repositories."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from varde_data.backends.sqlite.messages import (
    SQLiteMessages,
)
from varde_data.backends.sqlite.messages import (
    factory as sqlite_factory,
)
from varde_data.errors import Locked
from varde_data.locking import file_lock
from varde_data.records.messages import (
    Delivery,
    DeliveryOutcome,
    Message,
    NewMessage,
    ReaderResolver,
    RelayEvent,
)
from varde_data.version import Cursor

if TYPE_CHECKING:
    from varde_data.backends.files.messages import FilesMessages

_LOCK_TIMEOUT = 0.25
_HOOK_LOCK_TIMEOUT = 0.05
_STATE_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS mirror_state ("
    "stream TEXT PRIMARY KEY, position TEXT NOT NULL, lag INTEGER NOT NULL DEFAULT 0)"
)
_PARITY_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS parity ("
    "day TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL, "
    "UNIQUE(day, kind, detail))"
)
_PARITY_INDEX = "CREATE INDEX IF NOT EXISTS parity_day_kind ON parity(day,kind)"
_READ_METHODS = frozenset(
    {
        "head",
        "read_since",
        "read_all",
        "deliveries",
        "status_events",
        "pending_by_address",
        "peek_unread",
        "message_ids",
        "reader_position",
        "unread",
        "concluded_addresses",
        "status",
        "version",
        "read_note",
    }
)


def resume_position(position: str | None) -> str:
    """Return the stored stream offset, using the stream's origin when absent."""
    return position if position is not None else "0"


def diff_reads(
    source: Iterable[Message], mirror: Iterable[Message]
) -> tuple[Message, ...]:
    """Return source messages that are absent or different in the mirror."""
    mirrored = {message.id: message for message in mirror}
    return tuple(
        message
        for message in source
        if message.id is None or mirrored.get(message.id) != message
    )


class MirrorMessages:
    """Apply writes to a primary and replay its persisted stream positions."""

    def __init__(
        self,
        working: Path,
        primary_name: str,
        mirror_name: str,
        *,
        resolver: ReaderResolver | None = None,
        busy_timeout: float = 30,
        mode_generation: int | None = None,
    ) -> None:
        self.working = working
        self.primary_name = primary_name
        self.mirror_name = mirror_name
        self.mode_generation = mode_generation
        if resolver is None:
            from varde_data.backends.files.slots_reader import SlotReader

            resolver = SlotReader(working)
        self.resolver = resolver
        self.busy_timeout = busy_timeout
        self.mode_marker_mtime: int | None = None
        if mode_generation is not None:
            from varde_data.store_mode import marker_path

            self.mode_marker_mtime = marker_path(working).stat().st_mtime_ns
        self.primary = self._backend(working, primary_name, resolver, busy_timeout)
        self._mirror: FilesMessages | SQLiteMessages | None = None
        self._state_path = working / ".cache" / "inbox" / "messages.sqlite3"
        self._lock_path = working / ".cache" / "inbox" / "mirror.lock"
        self._state_uncertain = False
        self._known_mirror_ids: set[str] | None = None
        self._initialize_state()

    @property
    def mirror(self) -> FilesMessages | SQLiteMessages:
        """Open the secondary backend only when synchronization needs it."""
        if self._mirror is None:
            self._mirror = self._backend(
                self.working,
                self.mirror_name,
                self.resolver,
                min(self.busy_timeout, _LOCK_TIMEOUT),
            )
        return self._mirror

    @staticmethod
    def _backend(
        working: Path, name: str, resolver: ReaderResolver | None, timeout: float
    ) -> FilesMessages | SQLiteMessages:
        if name == "files":
            from varde_data.backends.files.messages import FilesMessages

            return FilesMessages(working, resolver, lock_timeout=timeout)
        return sqlite_factory(working, resolver, busy_timeout=timeout)

    def _initialize_state(self) -> None:
        try:
            with (
                closing(sqlite3.connect(self._state_path, timeout=_LOCK_TIMEOUT)) as db,
                db,
            ):
                existing = {
                    (str(row[0]), str(row[1]))
                    for row in db.execute(
                        "SELECT type,name FROM sqlite_master WHERE name IN "
                        "('mirror_state','parity','parity_day_kind')"
                    )
                }
                required = {
                    ("table", "mirror_state"),
                    ("table", "parity"),
                    ("index", "parity_day_kind"),
                }
                if not required <= existing:
                    db.execute(_STATE_SCHEMA)
                    db.execute(_PARITY_SCHEMA)
                    db.execute(_PARITY_INDEX)
        except sqlite3.Error:
            self._state_uncertain = True

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            return sqlite3.connect(
                f"{self._state_path.as_uri()}?mode=ro", uri=True, timeout=_LOCK_TIMEOUT
            )
        return sqlite3.connect(self._state_path, timeout=_LOCK_TIMEOUT)

    def _state(self, key: str) -> tuple[str, int] | None:
        try:
            with closing(self._connect(readonly=True)) as db:
                return db.execute(
                    "SELECT position, lag FROM mirror_state WHERE stream=?", (key,)
                ).fetchone()
        except sqlite3.Error:
            self._state_uncertain = True
            return None

    def _write_state(self, key: str, position: str, lag: int = 0) -> bool:
        try:
            with closing(self._connect()) as db, db:
                db.execute(
                    "INSERT INTO mirror_state(stream,position,lag) VALUES(?,?,?) "
                    "ON CONFLICT(stream) DO UPDATE SET "
                    "position=excluded.position,lag=excluded.lag",
                    (key, position, lag),
                )
        except sqlite3.Error:
            self._state_uncertain = True
            return False
        else:
            return True

    def _mark_pending(self, method: str, args: tuple[Any, ...]) -> int | None:
        try:
            with closing(self._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                return self._mark_pending_in(db, method, args)
        except sqlite3.Error:
            self._state_uncertain = True
            return None

    def _mark_pending_in(
        self, db: sqlite3.Connection, method: str, args: tuple[Any, ...]
    ) -> int:
        row = db.execute(
            "SELECT position FROM mirror_state WHERE stream='epoch'"
        ).fetchone()
        epoch = int(row[0]) + 1 if row else 1
        db.execute(
            "INSERT INTO mirror_state(stream,position,lag) VALUES('epoch',?,0) "
            "ON CONFLICT(stream) DO UPDATE SET position=excluded.position",
            (str(epoch),),
        )
        for stream in self._streams_for(method, args):
            db.execute(
                "INSERT INTO mirror_state(stream,position,lag) VALUES(?,?,1) "
                "ON CONFLICT(stream) DO UPDATE SET lag=1",
                (stream, ""),
            )
        for reader in self._readers_for(method, args):
            db.execute(
                "INSERT INTO mirror_state(stream,position,lag) "
                "VALUES(?,?,1) ON CONFLICT(stream) DO UPDATE SET lag=1",
                (f"reader-pending:{reader}", ""),
            )
        return epoch

    @staticmethod
    def _streams_for(method: str, args: tuple[Any, ...]) -> tuple[str, ...]:
        if method in {"append", "import_messages"}:
            return ("messages",)
        if method in {
            "claim_unread",
            "record_delivery",
            "record_relay_event",
            "ack",
            "import_deliveries",
        }:
            return ("deliveries",)
        if method in {"mark_concluded", "import_concluded"}:
            return ("concluded",)
        if method in {"register_reader", "import_reader_position"}:
            return ("readers",)
        if method == "commit_cursor":
            return ("cursors",)
        return ()

    @staticmethod
    def _reader_for(method: str, args: tuple[Any, ...]) -> str | None:
        if method in {
            "claim_unread",
            "record_delivery",
            "ack",
            "register_reader",
            "import_reader_position",
            "commit_cursor",
        }:
            value = args[0] if method != "record_delivery" else args[0].reader
            return str(value)
        if method == "record_relay_event":
            return args[0].reader
        return None

    @classmethod
    def _readers_for(cls, method: str, args: tuple[Any, ...]) -> set[str]:
        if method == "import_deliveries":
            return {delivery.reader for delivery in args[0]}
        reader = cls._reader_for(method, args)
        return {reader} if reader else set()

    def mirror_lag(self) -> int:
        try:
            with closing(self._connect(readonly=True)) as db:
                exists = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='mirror_state'"
                ).fetchone()
                if exists is None:
                    return 1 if self._state_uncertain else 0
                row = db.execute(
                    "SELECT COALESCE(SUM(lag),0) FROM mirror_state"
                ).fetchone()
                return max(int(row[0]) if row else 0, int(self._state_uncertain))
        except sqlite3.Error as exc:
            raise Locked(
                "message mirror state is uncertain; retry the operation"
            ) from exc

    def _write(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self.mode_generation is not None:
            from varde_data.messages import open_messages
            from varde_data.store_mode import (
                marker_path,
                parse_store_mode_record,
                store_mode_read_lock,
            )

            with store_mode_read_lock(self.working, timeout=self.busy_timeout):
                path = marker_path(self.working)
                current_mtime = path.stat().st_mtime_ns
                if current_mtime == self.mode_marker_mtime:
                    return self._write_current(method, *args, **kwargs)
                current = parse_store_mode_record(path.read_text(encoding="utf-8"))
                if current.generation == self.mode_generation:
                    self.mode_marker_mtime = current_mtime
                    return self._write_current(method, *args, **kwargs)
            repository = open_messages(
                self.working,
                current.primary,
                resolver=self.resolver,
                busy_timeout=self.busy_timeout,
            )
            return getattr(repository, method)(*args, **kwargs)
        return self._write_current(method, *args, **kwargs)

    def _write_current(self, method: str, *args: Any, **kwargs: Any) -> Any:
        hook_claim = self._is_hook_claim(method, args)
        if hook_claim and self.primary_name == "files":
            return self._claim_files_hook(args, kwargs)
        if hook_claim and isinstance(self.primary, SQLiteMessages):
            return self._claim_sqlite_hook(args, kwargs)
        if hook_claim and not self.primary.peek_unread(args[0]):
            return ()
        epoch = self._mark_pending(method, args)
        timeout = (
            _HOOK_LOCK_TIMEOUT if self._is_hook_claim(method, args) else _LOCK_TIMEOUT
        )
        lock = file_lock(self._lock_path, timeout=timeout)
        try:
            lock.__enter__()
        except (Locked, OSError) as exc:
            # The durable pending marker precedes this unlocked primary write.
            result = getattr(self.primary, method)(*args, **kwargs)
            self._mark_pending(method, args)
            self._record_event("lag", method, type(exc).__name__)
            return result
        try:
            result = getattr(self.primary, method)(*args, **kwargs)
            if hook_claim:
                return result
            try:
                self._replay(method, args, kwargs, result)
                self._sync(epoch)
            except Exception as exc:  # noqa: BLE001
                self._record_event("mirror-failure", method, type(exc).__name__)
                self._record_event("lag", method, type(exc).__name__)
            return result
        finally:
            lock.__exit__(None, None, None)

    @staticmethod
    def _is_hook_claim(method: str, args: tuple[Any, ...]) -> bool:
        return method == "claim_unread" and len(args) > 2 and args[2] == "hook"

    def _claim_files_hook(
        self, args: tuple[Any, ...], kwargs: Mapping[str, Any]
    ) -> Any:
        primary = cast("FilesMessages", self.primary)
        lock = file_lock(self._lock_path, timeout=_HOOK_LOCK_TIMEOUT)
        try:
            lock.__enter__()
        except (Locked, OSError) as exc:
            if not primary.peek_unread(args[0]):
                return ()
            self._mark_pending("claim_unread", args)
            result = primary.claim_unread(*args, **kwargs)
            self._mark_pending("claim_unread", args)
            self._record_event("lag", "claim_unread", type(exc).__name__)
            return result
        try:
            return primary.claim_unread_with_pending(
                *args,
                **kwargs,
                before_claim=lambda: self._mark_pending("claim_unread", args),
            )
        finally:
            lock.__exit__(None, None, None)

    def _claim_sqlite_hook(
        self, args: tuple[Any, ...], kwargs: Mapping[str, Any]
    ) -> Any:
        primary = cast("SQLiteMessages", self.primary)
        lock = file_lock(self._lock_path, timeout=_HOOK_LOCK_TIMEOUT)
        try:
            lock.__enter__()
        except (Locked, OSError) as exc:
            result = primary.claim_unread_with_pending(
                *args,
                **kwargs,
                before_claim=lambda db: self._mark_pending_in(db, "claim_unread", args),
            )
            if result:
                self._record_event("lag", "claim_unread", type(exc).__name__)
            return result
        try:
            return primary.claim_unread_with_pending(
                *args,
                **kwargs,
                before_claim=lambda db: self._mark_pending_in(db, "claim_unread", args),
            )
        finally:
            lock.__exit__(None, None, None)

    def _sync(self, epoch: int | None = None) -> bool:
        start_epoch = self._epoch()
        pending = self._pending_streams()
        pending, start_epoch, synchronized = self._sync_pending(pending, start_epoch)
        if synchronized:
            return True
        if self._state_uncertain:
            pending |= {"messages", "deliveries", "concluded", "readers", "cursors"}
        progress: dict[str, str] = {}
        message_key = f"messages:{self.primary_name}"
        if "messages" in pending or self._state(message_key) is None:
            start = resume_position(
                self._position("messages", backend=self.primary_name)
            )
            head = self.primary.head()
            rows = self.primary.read_since(Cursor(start)).records
            self._check_known_ids(rows)
            if rows:
                self.mirror.import_messages(rows)
            progress[message_key] = head.value
        delivery_key = f"deliveries:{self.primary_name}"
        if "deliveries" in pending or self._state(delivery_key) is None:
            rows, position = self._deliveries_after(
                resume_position(self._position("deliveries", backend=self.primary_name))
            )
            mirror_position = self._transfer_deliveries(rows)
            progress[delivery_key] = position
            progress[f"deliveries:{self.mirror_name}"] = mirror_position
        if "concluded" in pending or self._state("concluded:position") is None:
            current = self.primary.concluded_addresses()
            mirrored = self.mirror.concluded_addresses()
            self.mirror.import_concluded(current - mirrored)
            progress["concluded:position"] = "1"
        if (
            "readers" in pending
            or "cursors" in pending
            or bool(self._pending_readers())
            or "reader-init" not in self._positions_present()
            or self._state_uncertain
        ):
            readers = self._pending_readers()
            if (
                "reader-init" not in self._positions_present()
                or self._state_uncertain
                or "readers" in pending
                or "cursors" in pending
            ):
                readers |= self._all_readers()
            for reader in readers:
                self._sync_reader_position(reader)
                progress[f"reader:{reader}"] = "1"
            progress["reader-init"] = "1"
        if (
            "cursors" in pending
            or bool(self._pending_readers())
            or "cursor-init" not in self._positions_present()
        ):
            cursor_readers = self._pending_readers()
            if "cursors" in pending or "cursor-init" not in self._positions_present():
                cursor_readers |= self._all_readers()
            for reader in cursor_readers:
                cursor = self._primary_cursor(reader)
                mirror_cursor = self._cursor_for_id(reader, cursor)
                self.mirror.import_cursor(reader, mirror_cursor)
            progress["cursors:position"] = "1"
            progress["cursor-init"] = "1"
        end_epoch = self._epoch()
        expected = epoch if epoch is not None else start_epoch
        if end_epoch != expected:
            return False
        pending_readers = self._pending_readers()
        if (epoch is None or self._state_uncertain) and not self.is_synchronized():
            self._mark_all_pending()
            return False
        if not self._clear_pending(pending, pending_readers, expected, progress):
            return False
        self._state_uncertain = False
        return self.mirror_lag() == 0

    def _sync_reader_position(self, reader: str) -> None:
        reader = self.primary._resolve(reader)
        position = self.primary.reader_position(reader)
        if position is None:
            self.primary.register_reader(reader, from_start=True)
            position = self.primary.reader_position(reader)
        if position is None:
            self.mirror.register_reader(reader, from_start=True)
        self.mirror.import_reader_position(reader, position)

    def _sync_pending(
        self, pending: set[str], start_epoch: int
    ) -> tuple[set[str], int, bool]:
        if pending or self._state_uncertain:
            return pending, start_epoch, False
        if self.is_synchronized():
            return pending, start_epoch, True
        if not self._mark_all_pending():
            return pending, start_epoch, False
        return self._pending_streams(), self._epoch(), False

    def _mark_all_pending(self) -> bool:
        streams = ("messages", "deliveries", "concluded", "readers", "cursors")
        try:
            with closing(self._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT position FROM mirror_state WHERE stream='epoch'"
                ).fetchone()
                epoch = int(row[0]) + 1 if row else 1
                db.execute(
                    "INSERT INTO mirror_state(stream,position,lag) VALUES('epoch',?,0) "
                    "ON CONFLICT(stream) DO UPDATE SET position=excluded.position",
                    (str(epoch),),
                )
                db.executemany(
                    "INSERT INTO mirror_state(stream,position,lag) VALUES(?,?,1) "
                    "ON CONFLICT(stream) DO UPDATE SET lag=1",
                    ((stream, "") for stream in streams),
                )
        except sqlite3.Error:
            self._state_uncertain = True
            return False
        return True

    def _epoch(self) -> int:
        state = self._state("epoch")
        return int(state[0]) if state else 0

    def _pending_streams(self) -> set[str]:
        try:
            with closing(self._connect(readonly=True)) as db:
                return {
                    str(row[0])
                    for row in db.execute(
                        "SELECT stream FROM mirror_state WHERE lag=1 "
                        "AND stream NOT LIKE 'reader-pending:%'"
                    )
                }
        except sqlite3.Error:
            self._state_uncertain = True
            return set()

    def _pending_readers(self) -> set[str]:
        try:
            with closing(self._connect(readonly=True)) as db:
                return {
                    str(row[0]).removeprefix("reader-pending:")
                    for row in db.execute(
                        "SELECT stream FROM mirror_state "
                        "WHERE lag=1 AND stream LIKE 'reader-pending:%'"
                    )
                }
        except sqlite3.Error:
            self._state_uncertain = True
            return set()

    def _positions_present(self) -> set[str]:
        try:
            with closing(self._connect(readonly=True)) as db:
                return {
                    str(row[0]) for row in db.execute("SELECT stream FROM mirror_state")
                }
        except sqlite3.Error:
            self._state_uncertain = True
            return set()

    def _position(self, stream: str, *, backend: str) -> str | None:
        state = self._state(f"{stream}:{backend}")
        if state is None:
            return None
        return state[0]

    def _lag(self, stream: str) -> int:
        state = self._state(stream)
        return state[1] if state else 0

    def _clear_pending(
        self,
        streams: set[str],
        readers: set[str],
        expected_epoch: int,
        progress: Mapping[str, str],
    ) -> bool:
        try:
            with closing(self._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT position FROM mirror_state WHERE stream='epoch'"
                ).fetchone()
                if row is None or int(row[0]) != expected_epoch:
                    return False
                db.executemany(
                    "INSERT INTO mirror_state(stream,position,lag) VALUES(?,?,0) "
                    "ON CONFLICT(stream) DO UPDATE SET "
                    "position=excluded.position,lag=0",
                    ((key, value) for key, value in progress.items()),
                )
                for stream in streams:
                    db.execute(
                        "UPDATE mirror_state SET lag=0 WHERE stream=?", (stream,)
                    )
                for reader in readers:
                    db.execute(
                        "UPDATE mirror_state SET lag=0 WHERE stream=?",
                        (f"reader-pending:{reader}",),
                    )
        except sqlite3.Error:
            self._state_uncertain = True
            return False
        else:
            return True

    def _deliveries_after(self, position: str) -> tuple[tuple[Delivery, ...], str]:
        return self._repository_deliveries_after(self.primary, position)

    def _repository_deliveries_after(
        self,
        repository: FilesMessages | SQLiteMessages,
        position: str,
    ) -> tuple[tuple[Delivery, ...], str]:
        if isinstance(repository, SQLiteMessages):
            try:
                start = int(position)
            except ValueError:
                start = 0
            with repository._connection() as db:
                db.execute("BEGIN")
                rows = db.execute(
                    "SELECT * FROM deliveries WHERE seq>? ORDER BY seq", (start,)
                ).fetchall()
                current = db.execute(
                    "SELECT COALESCE(MAX(seq),0) FROM deliveries"
                ).fetchone()[0]
            return tuple(repository._delivery(row) for row in rows), str(current)
        return self._files_deliveries_after(repository, position)

    @staticmethod
    def _files_deliveries_after(
        repository: FilesMessages, position: str
    ) -> tuple[tuple[Delivery, ...], str]:
        path = repository.inbox / "deliveries.jsonl"
        offset = max(0, int(position or 0))
        deliveries: list[Delivery] = []
        with suppress(FileNotFoundError), path.open("rb") as stream:
            stream.seek(offset)
            while line := stream.readline():
                if not line.endswith(b"\n"):
                    break
                row = json.loads(line)
                known = {
                    "message_id",
                    "reader",
                    "session",
                    "via",
                    "event",
                    "at",
                    "action_created_at",
                    "reason",
                }
                deliveries.append(
                    Delivery(
                        row["message_id"],
                        row["reader"],
                        row.get("session", ""),
                        row.get("via", "cli"),
                        row["event"],
                        row["at"],
                        row.get("action_created_at"),
                        row.get("reason"),
                        {
                            key: value
                            for key, value in row.items()
                            if key not in known and isinstance(value, str)
                        },
                    )
                )
                offset = stream.tell()
        return tuple(deliveries), str(offset)

    def _transfer_deliveries(self, source: tuple[Delivery, ...]) -> str:
        mirror_position = resume_position(
            self._position("deliveries", backend=self.mirror_name)
        )
        mirrored_tail, target_position = self._repository_deliveries_after(
            self.mirror, mirror_position
        )
        if (
            len(mirrored_tail) > len(source)
            or mirrored_tail != source[: len(mirrored_tail)]
        ):
            self._record_event("divergence", "deliveries", "resume-mismatch")
            raise ValueError("mirror delivery position differs from primary")
        missing = source[len(mirrored_tail) :]
        if missing:
            if isinstance(self.mirror, SQLiteMessages):
                with self.mirror._connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    for delivery in missing:
                        self.mirror._insert_delivery(db, delivery, delivery.reader)
            else:
                with file_lock(
                    self.mirror.inbox / ".deliveries.lock", timeout=_LOCK_TIMEOUT
                ):
                    self.mirror._append_deliveries_locked(missing)
            _, target_position = self._repository_deliveries_after(
                self.mirror, target_position
            )
        return target_position

    def _check_known_ids(self, rows: tuple[Message, ...]) -> None:
        if not rows:
            return
        if self._known_mirror_ids is None:
            self._known_mirror_ids = self.mirror.message_ids()
        candidates = [row for row in rows if row.id in self._known_mirror_ids]
        if not candidates:
            self._known_mirror_ids.update(
                message.id for message in rows if message.id is not None
            )
            return
        mirror_rows = self.mirror.read_all().records
        differences = diff_reads(
            candidates, (row for row in mirror_rows if row.id in self._known_mirror_ids)
        )
        for row in differences:
            self._record_event("divergence", "message", str(row.id))
        self._known_mirror_ids.update(
            message.id for message in rows if message.id is not None
        )

    def _all_readers(self) -> set[str]:
        return self._readers(self.primary) | self._readers(self.mirror)

    @staticmethod
    def _readers(repository: FilesMessages | SQLiteMessages) -> set[str]:
        if isinstance(repository, SQLiteMessages):
            with repository._connection() as db:
                return {
                    str(row[0])
                    for row in db.execute(
                        "SELECT reader FROM readers "
                        "UNION SELECT reader FROM cursor_positions"
                    )
                }
        readers: set[str] = set()
        index = repository.inbox / "index"
        if index.exists():
            readers.update(
                path.stem
                for path in index.glob("*.json")
                if not path.name.endswith(".delivered.json")
            )
        cursors = repository.inbox / "cursors"
        if cursors.exists():
            readers.update(
                path.name
                for path in cursors.iterdir()
                if path.is_file()
                and not (path.name.startswith(".") and path.name.endswith(".tmp"))
            )
        return readers

    def _primary_cursor(self, reader: str) -> str | None:
        return self._cursor_id(self.primary, reader)

    @staticmethod
    def _cursor_id(
        repository: FilesMessages | SQLiteMessages, reader: str
    ) -> str | None:
        reader = repository._resolve(reader)
        if isinstance(repository, SQLiteMessages):
            with repository._connection() as db:
                row = db.execute(
                    "SELECT m.id FROM cursor_positions c LEFT JOIN messages m "
                    "ON m.seq=c.position WHERE c.reader=?",
                    (reader,),
                ).fetchone()
            return repository.reader_position(reader) if row is None else row[0]
        path = repository.inbox / "cursors" / reader
        try:
            offset = int(path.read_text(encoding="ascii"))
        except OSError:
            return None
        except ValueError:
            return None
        return MirrorMessages._files_id_at_offset(repository, offset)

    @staticmethod
    def _files_id_at_offset(repository: FilesMessages, offset: int) -> str | None:
        path = repository.inbox / "messages.jsonl"
        current = 0
        last = None
        try:
            with path.open("rb") as stream:
                while current < offset and (line := stream.readline()):
                    current += len(line)
                    raw = json.loads(line)
                    last = raw.get("id", last)
        except OSError:
            return last
        except ValueError:
            return last
        return last

    def _cursor_for_id(self, reader: str, message_id: str | None) -> Cursor:
        if message_id is None:
            return Cursor("0")
        if isinstance(self.mirror, SQLiteMessages):
            with self.mirror._connection() as db:
                row = db.execute(
                    "SELECT seq FROM messages WHERE id=?", (message_id,)
                ).fetchone()
            return Cursor(str(row[0] if row else 0))
        offset = 0
        path = self.mirror.inbox / "messages.jsonl"
        with path.open("rb") as stream:
            while line := stream.readline():
                offset += len(line)
                if json.loads(line).get("id") == message_id:
                    return Cursor(str(offset))
        return Cursor("0")

    def _record_event(self, kind: str, stream: str, detail: str) -> None:
        try:
            with closing(self._connect()) as db, db:
                db.execute("DELETE FROM parity WHERE day < date('now','-30 days')")
                db.execute(
                    "INSERT INTO parity(day,kind,detail) "
                    "SELECT date('now'),?,? WHERE NOT EXISTS ("
                    "SELECT 1 FROM parity WHERE day=date('now') AND kind=? "
                    "AND detail=?)",
                    (kind, f"{stream}:{detail}", kind, f"{stream}:{detail}"),
                )
        except sqlite3.Error:
            self._state_uncertain = True

    def _replay(
        self, method: str, args: tuple[Any, ...], kwargs: Mapping[str, Any], result: Any
    ) -> None:
        if method == "import_messages":
            self._check_known_ids(
                tuple(row for row in args[0] if isinstance(row, Message))
            )
            self.mirror.import_messages(args[0])

    def sync(self) -> bool:
        try:
            with file_lock(self._lock_path, timeout=_LOCK_TIMEOUT):
                return self._sync()
        except Exception:  # noqa: BLE001
            self._record_event("lag", "sync", "lock-timeout")
            return False

    def is_synchronized(self) -> bool:
        try:
            if self.primary.read_all().records != self.mirror.read_all().records:
                return False
            if self.primary.deliveries() != self.mirror.deliveries():
                return False
            if self.primary.concluded_addresses() != self.mirror.concluded_addresses():
                return False
            for reader in self._all_readers():
                if self.primary.reader_position(reader) != self.mirror.reader_position(
                    reader
                ):
                    return False
                if self._cursor_id(self.primary, reader) != self._cursor_id(
                    self.mirror, reader
                ):
                    return False
        except Exception:  # noqa: BLE001
            return False
        else:
            return True

    def compare(self) -> bool:
        """Compare persisted state outside the prompt-hook path, without raising."""
        try:
            with file_lock(self._lock_path, timeout=_LOCK_TIMEOUT):
                if not self._sync():
                    self._record_event("compared", "daily", "count")
                    self._record_event("lag", "comparison", "pending")
                    return False
                equal = self.is_synchronized()
                self._record_event("compared", "daily", "count")
                if not equal:
                    self._record_event("divergence", "comparison", "state")
                return equal
        except Exception:  # noqa: BLE001
            self._record_event("mirror-failure", "comparison", "error")
            return False

    def append(self, message: NewMessage) -> Message:
        return self._write("append", message)

    def claim_unread(
        self, reader: str, session: str, via: str, now: str | None = None
    ) -> tuple[Message, ...]:
        return self._write("claim_unread", reader, session, via, now)

    def record_delivery(self, delivery: Delivery) -> DeliveryOutcome:
        return self._write("record_delivery", delivery)

    def record_relay_event(self, event: RelayEvent) -> DeliveryOutcome:
        return self._write("record_relay_event", event)

    def ack(self, reader: str, message_id: str, *, now: str | None = None) -> bool:
        return self._write("ack", reader, message_id, now=now)

    def mark_concluded(self, address: str) -> None:
        self._write("mark_concluded", address)

    def register_reader(self, reader: str, from_start: bool) -> None:
        self._write("register_reader", reader, from_start)

    def import_messages(
        self, rows: Iterable[Message | Mapping[str, object]]
    ) -> tuple[Message | Mapping[str, object], ...]:
        return self._write("import_messages", tuple(rows))

    def import_deliveries(self, rows: Iterable[Delivery]) -> None:
        self._write("import_deliveries", tuple(rows))

    def import_concluded(self, addresses: Iterable[str]) -> None:
        self._write("import_concluded", tuple(addresses))

    def import_reader_position(self, reader: str, message_id: str | None) -> None:
        self._write("import_reader_position", reader, message_id)

    def commit_cursor(self, reader: str, cursor: Cursor) -> None:
        self._write("commit_cursor", reader, cursor)

    def parity_report(self, window: int = 7) -> dict[str, int]:
        try:
            with closing(self._connect()) as db:
                rows = db.execute(
                    "SELECT kind, count(*) FROM parity "
                    "WHERE day >= date('now', ?) GROUP BY kind",
                    (f"-{window} days",),
                ).fetchall()
            return {str(kind): int(count) for kind, count in rows}
        except sqlite3.Error:
            return {"mirror-failure": 1}

    def __getattr__(self, name: str) -> Any:
        if name not in _READ_METHODS:
            raise AttributeError(name)
        return getattr(self.primary, name)
