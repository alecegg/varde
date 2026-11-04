"""Append-only files implementation of the message repository."""

from __future__ import annotations

import io
import json
import os
import secrets
from collections.abc import Callable, Iterable, Mapping
from contextlib import ExitStack
from pathlib import Path
from threading import Lock

from varde_data.backends.files.slots_reader import SlotReader
from varde_data.backends.files.store_guard import ensure_files_store_writable
from varde_data.errors import Invalid, NotFound
from varde_data.locking import atomic_write, file_lock, read_complete_lines
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
    parse_messages,
    timestamp,
    validate_address,
    validate_message,
    validate_message_id,
)
from varde_data.store_mode import StoreModeRecord, read_store_mode
from varde_data.version import Cursor, Version, files_version


def _row_id(row: Message | Mapping[str, object]) -> str | None:
    if isinstance(row, Message):
        return row.id
    message_id = row.get("id")
    return message_id if isinstance(message_id, str) else None


def _message_wire(row: Message | Mapping[str, object]) -> dict[str, object]:
    if not isinstance(row, Message):
        return dict(row)
    return {
        "ts": row.ts,
        "from": row.from_,
        "to": row.to,
        "kind": row.kind,
        "text": row.text,
        **({"notes": row.notes} if row.notes is not None else {}),
        **({"reply_to": row.reply_to} if row.reply_to is not None else {}),
        "id": row.id,
    }


def _delivery_wire(delivery: Delivery) -> dict[str, object]:
    row: dict[str, object] = {
        "message_id": delivery.message_id,
        "reader": delivery.reader,
        "session": delivery.session,
        "via": delivery.via,
        "event": delivery.event,
        "at": delivery.at,
    }
    if delivery.action_created_at is not None:
        row["action_created_at"] = delivery.action_created_at
    if delivery.reason is not None:
        row["reason"] = delivery.reason
    row.update(
        {
            key: value
            for key, value in delivery.details.items()
            if key not in row and isinstance(value, str)
        }
    )
    return row


def _delivery_identity(delivery: Delivery) -> str:
    """Identify the complete persisted row; identical rows collapse on replay."""
    return json.dumps(_delivery_wire(delivery), sort_keys=True, separators=(",", ":"))


TAIL_CHECK_LIMIT = 4096


def _last_line(chunk: bytes) -> bytes:
    """Last newline-terminated record of `chunk`, capped for cheap re-checks."""
    start = chunk.rfind(b"\n", 0, len(chunk) - 1) + 1
    return chunk[max(start, len(chunk) - TAIL_CHECK_LIMIT) :]


class FilesMessages:
    def __init__(
        self,
        working: Path,
        resolver: ReaderResolver | None = None,
        *,
        lock_timeout: float = 30,
    ) -> None:
        self._initialize(working, resolver, read_store_mode(working), lock_timeout)

    @classmethod
    def from_store_mode(
        cls,
        working: Path,
        resolver: ReaderResolver | None,
        record: StoreModeRecord | None,
        lock_timeout: float = 30,
    ) -> FilesMessages:
        """Open using a marker already read and cross-checked by the factory."""
        repository = cls.__new__(cls)
        repository._initialize(working, resolver, record, lock_timeout)
        return repository

    def _initialize(
        self,
        working: Path,
        resolver: ReaderResolver | None,
        record: StoreModeRecord | None,
        lock_timeout: float = 30,
    ) -> None:
        ensure_files_store_writable(working, record)
        self.working = working
        self.inbox = working / ".cache" / "inbox"
        self._resolver = resolver or SlotReader(working)
        self.lock_timeout = lock_timeout
        self._message_ids_cache: set[str] = set()
        self._message_ids_cache_size: int | None = None
        self._delivery_cache_lock = Lock()
        self._delivery_cache_signature: tuple[int, int, int, int] | None = None
        self._delivery_cache_prefix = b""
        self._delivery_cache_tail = b""
        self._delivery_cache_offset = 0
        self._delivery_cache_rows: list[Delivery] = []
        self._delivery_cache_errors: list[str] = []
        self._message_cache_signature: tuple[int, int, int, int] | None = None
        self._message_cache_prefix = b""
        self._message_cache_tail = b""
        self._message_cache_offset = 0
        self._message_cache_tail = b""
        self._message_cache_line = 0
        self._message_cache_records: list[Message] = []
        self._message_cache_skipped: list[str] = []

    @property
    def _messages(self) -> Path:
        return self.inbox / "messages.jsonl"

    @property
    def _deliveries(self) -> Path:
        return self.inbox / "deliveries.jsonl"

    def _resolve(self, reader: str) -> str:
        validate_address(reader, "reader")
        return self._resolver.resolve(reader)

    @staticmethod
    def _resolve_with(reader: str, resolver: ReaderResolver) -> str:
        validate_address(reader, "reader")
        return resolver.resolve(reader)

    def _resolver_snapshot(self) -> ReaderResolver:
        if isinstance(self._resolver, SlotReader):
            return self._resolver.snapshot()
        return self._resolver

    def _lock(self, reader: str) -> Path:
        return self.inbox / f".{reader}.lock"

    def _read_messages(self) -> ReadResult:
        with self._delivery_cache_lock:
            self._refresh_message_cache()
            return ReadResult(
                tuple(self._message_cache_records),
                tuple(self._message_cache_skipped),
            )

    def _refresh_message_cache(self) -> None:
        try:
            info = self._messages.stat()
        except FileNotFoundError:
            self._reset_message_cache(None)
            return
        signature = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)
        prior = self._message_cache_signature
        prefix_changed = not self._cache_intact(
            self._messages,
            self._message_cache_prefix,
            self._message_cache_tail,
            self._message_cache_offset,
        )
        changed_in_place = (
            prior is not None
            and signature[:2] == prior[:2]
            and signature[3] == prior[3]
            and signature[2] != prior[2]
        )
        if (
            prior is None
            or signature[:2] != prior[:2]
            or signature[3] < self._message_cache_offset
            or changed_in_place
            or prefix_changed
        ):
            self._reset_message_cache(signature)
        if signature[3] > self._message_cache_offset:
            with self._messages.open("rb") as stream:
                stream.seek(self._message_cache_offset)
                appended = stream.read(signature[3] - self._message_cache_offset)
            complete_length = appended.rfind(b"\n") + 1
            if complete_length:
                parsed = parse_messages(
                    appended[:complete_length],
                    start_offset=self._message_cache_offset,
                    start_line=self._message_cache_line,
                )
                self._message_cache_records.extend(parsed.records)
                self._message_cache_skipped.extend(parsed.skipped)
                self._message_cache_line += appended[:complete_length].count(b"\n")
                self._message_cache_offset += complete_length
                self._message_cache_tail = _last_line(appended[:complete_length])
        self._message_cache_signature = signature
        if not self._message_cache_prefix and self._message_cache_offset:
            self._message_cache_prefix = self._read_cache_prefix(self._messages)

    def _reset_message_cache(self, signature: tuple[int, int, int, int] | None) -> None:
        self._message_cache_signature = signature
        self._message_cache_prefix = (
            self._read_cache_prefix(self._messages) if signature else b""
        )
        self._message_cache_offset = 0
        self._message_cache_tail = b""
        self._message_cache_line = 0
        self._message_cache_records.clear()
        self._message_cache_skipped.clear()

    def _deliveries_read(self, *, strict: bool = False) -> tuple[Delivery, ...]:
        with self._delivery_cache_lock:
            self._refresh_delivery_cache()
            if strict and self._delivery_cache_errors:
                raise Invalid(self._delivery_cache_errors[0])
            return tuple(self._delivery_cache_rows)

    def _refresh_delivery_cache(self) -> None:
        try:
            info = self._deliveries.stat()
        except FileNotFoundError:
            self._reset_delivery_cache(None)
            return
        signature = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)
        prior = self._delivery_cache_signature
        prefix_changed = not self._cache_intact(
            self._deliveries,
            self._delivery_cache_prefix,
            self._delivery_cache_tail,
            self._delivery_cache_offset,
        )
        changed_in_place = (
            prior is not None
            and signature[:2] == prior[:2]
            and signature[3] == prior[3]
            and signature[2] != prior[2]
        )
        if (
            prior is None
            or signature[:2] != prior[:2]
            or signature[3] < self._delivery_cache_offset
            or changed_in_place
            or prefix_changed
        ):
            self._reset_delivery_cache(signature)
        if signature[3] > self._delivery_cache_offset:
            with self._deliveries.open("rb") as stream:
                stream.seek(self._delivery_cache_offset)
                appended = stream.read(signature[3] - self._delivery_cache_offset)
            complete_length = appended.rfind(b"\n") + 1
            if complete_length:
                for line in appended[:complete_length].splitlines():
                    self._cache_delivery_line(line)
                self._delivery_cache_offset += complete_length
                self._delivery_cache_tail = _last_line(appended[:complete_length])
        self._delivery_cache_signature = signature
        if not self._delivery_cache_prefix and self._delivery_cache_offset:
            self._delivery_cache_prefix = self._read_cache_prefix(self._deliveries)

    def _reset_delivery_cache(
        self, signature: tuple[int, int, int, int] | None
    ) -> None:
        self._delivery_cache_signature = signature
        self._delivery_cache_prefix = (
            self._read_cache_prefix(self._deliveries) if signature else b""
        )
        self._delivery_cache_offset = 0
        self._delivery_cache_tail = b""
        self._delivery_cache_rows.clear()
        self._delivery_cache_errors.clear()

    @staticmethod
    def _read_cache_prefix(path: Path) -> bytes:
        with path.open("rb") as stream:
            return stream.read(256)

    @staticmethod
    def _cache_intact(path: Path, prefix: bytes, tail: bytes, offset: int) -> bool:
        """True when the file still starts with the cached prefix and the last
        cached record still ends at the cached offset."""
        if not prefix:
            return True
        with path.open("rb") as stream:
            if stream.read(len(prefix)) != prefix:
                return False
            if not tail:
                return True
            stream.seek(offset - len(tail))
            return stream.read(len(tail)) == tail

    def _cache_delivery_line(self, line: bytes) -> None:
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                self._delivery_cache_errors.append(
                    "invalid delivery log row: delivery row must be an object"
                )
                return
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
            self._delivery_cache_rows.append(
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
                        if key not in known_fields and isinstance(value, str)
                    },
                )
            )
        except (ValueError, TypeError, KeyError) as exc:
            self._delivery_cache_errors.append(f"invalid delivery log row: {exc}")

    def _append_delivery(self, delivery: Delivery) -> None:
        self._append_deliveries_locked((delivery,))

    def _append_deliveries_locked(self, deliveries: Iterable[Delivery]) -> None:
        rows = tuple(_delivery_wire(delivery) for delivery in deliveries)
        if not rows:
            return
        self.inbox.mkdir(parents=True, exist_ok=True)
        payload = b"".join(
            json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows
        )
        if self._deliveries.exists() and self._deliveries.stat().st_size:
            with self._deliveries.open("rb") as stream:
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    payload = b"\n" + payload
        descriptor = os.open(
            self._deliveries, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644
        )
        try:
            if os.write(descriptor, payload) != len(payload):
                raise OSError("short append to deliveries log")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _cached_message_ids(self) -> set[str]:
        """Refresh the parsed id set only when an append changes file size."""
        try:
            size = self._messages.stat().st_size
        except FileNotFoundError:
            size = 0
        if self._message_ids_cache_size != size:
            self._message_ids_cache = self.message_ids()
            self._message_ids_cache_size = size
        return self._message_ids_cache

    def _watermark(self, reader: str) -> int:
        try:
            value = json.loads((self.inbox / "index" / f"{reader}.json").read_text())
            return max(0, int(value.get("watermark", 0)))
        except OSError, ValueError, TypeError, AttributeError:
            return 0

    def _seed_index(self, reader: str) -> int:
        path = self.inbox / "index" / f"{reader}.json"
        current = self._watermark(reader)
        if path.exists():
            return current
        try:
            cursor = max(
                0, int((self.inbox / "cursors" / reader).read_text().strip() or "0")
            )
        except OSError, ValueError:
            cursor = self._messages.stat().st_size if self._messages.exists() else 0
        self._write_watermark(reader, cursor)
        return cursor

    def _write_watermark(self, reader: str, value: int) -> None:
        path = self.inbox / "index" / f"{reader}.json"
        value = max(value, self._watermark(reader))
        atomic_write(path, json.dumps({"watermark": value}).encode(), mode=0o644)

    def _delivered_ids(
        self, reader: str, resolver: ReaderResolver | None = None
    ) -> set[str]:
        resolver = resolver or self._resolver_snapshot()
        cache = self.inbox / "index" / f"{reader}.delivered.json"
        addresses = sorted(resolver.addresses(reader))
        try:
            delivery_size = self._deliveries.stat().st_size
        except FileNotFoundError:
            delivery_size = 0
        try:
            values = json.loads(cache.read_text(encoding="utf-8"))
            if (
                isinstance(values, dict)
                and values.get("delivery_size") == delivery_size
                and values.get("addresses") == addresses
                and isinstance(values.get("ids"), list)
            ):
                return {value for value in values["ids"] if isinstance(value, str)}
            cached = (
                {value for value in values if isinstance(value, str)}
                if isinstance(values, list)
                else set()
            )
        except OSError, ValueError:
            cached = set()
        address_set = set(addresses)
        ids = {
            m.id for m in self._read_messages().records if m.to in address_set and m.id
        }
        events = {
            item.message_id
            for item in self._deliveries_read()
            if self._resolve_with(item.reader, resolver) == reader
            and item.event in {"delivered", "dropped", "legacy"}
            and item.message_id in ids
        }
        return cached | events

    def _peek_snapshot(
        self,
        reader: str,
        start: int = 0,
        resolver: ReaderResolver | None = None,
        delivered_ids: set[str] | None = None,
    ) -> tuple[tuple[Message, ...], int]:
        resolver = resolver or self._resolver_snapshot()
        addresses = resolver.addresses(reader)
        if len(addresses) > 1:
            start = 0
        raw = self._messages.read_bytes() if self._messages.exists() else b""
        complete = raw[: raw.rfind(b"\n") + 1] if raw else b""
        end = len(complete)
        parsed = parse_messages(complete[start:end], start_offset=start)
        delivered = (
            self._delivered_ids(reader, resolver)
            if delivered_ids is None
            else delivered_ids
        )
        messages = tuple(
            m for m in parsed.records if m.to in addresses and m.id not in delivered
        )
        return messages, end

    def _peek(self, reader: str, start: int = 0) -> tuple[Message, ...]:
        return self._peek_snapshot(reader, start)[0]

    def append(self, message: NewMessage) -> Message:
        validate_message(message)
        resolver = self._resolver_snapshot()
        reader = self._resolve_with(message.to, resolver)
        with file_lock(self._lock(reader), timeout=30):
            self._seed_index(reader)
        with file_lock(self.inbox / ".messages.lock", timeout=30):
            known = self._cached_message_ids()
            while True:
                message_id = "m-" + secrets.token_hex(4)
                if message_id not in known:
                    break
            stored = Message(
                message.ts or timestamp(),
                message.from_,
                message.to,
                message.kind,
                message.text,
                message.notes,
                message_id,
                None,
                message.reply_to,
            )
            row = {
                "ts": stored.ts,
                "from": stored.from_,
                "to": stored.to,
                "kind": stored.kind,
                "text": stored.text,
                **({"notes": stored.notes} if stored.notes is not None else {}),
                **(
                    {"reply_to": stored.reply_to} if stored.reply_to is not None else {}
                ),
                "id": stored.id,
            }
            self._append_message_locked(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode()
            )
            known.add(message_id)
            self._message_ids_cache_size = self._messages.stat().st_size
        return stored

    def head(self) -> Cursor:
        return Cursor(str(self._complete_offset()))

    def _complete_offset(self) -> int:
        try:
            raw = self._messages.read_bytes()
        except FileNotFoundError:
            return 0
        return raw.rfind(b"\n") + 1

    def read_since(self, cursor: Cursor) -> ReadResult:
        try:
            offset = int(cursor.value)
        except ValueError:
            raise Invalid("invalid message cursor") from None
        complete = self._complete_offset()
        if offset < 0 or offset > complete:
            raise Invalid("message cursor is outside the stream")
        raw = self._messages.read_bytes() if self._messages.exists() else b""
        return parse_messages(raw[offset:complete])

    def read_all(self) -> ReadResult:
        return self._read_messages()

    def deliveries(self) -> tuple[Delivery, ...]:
        return self._deliveries_read(strict=True)

    def status_events(self) -> tuple[Mapping[str, object], ...]:
        rows = []
        for line in read_complete_lines(self.inbox / "events.jsonl"):
            try:
                row = json.loads(line)
            except ValueError, UnicodeDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return tuple(rows)

    def pending_by_address(self) -> Mapping[str, tuple[Message, ...]]:
        resolver = self._resolver_snapshot()
        suppressed = {
            (self._resolve_with(d.reader, resolver), d.message_id)
            for d in self._deliveries_read()
            if d.event in {"delivered", "dropped", "legacy"}
        }
        result: dict[str, list[Message]] = {}
        for message in self._read_messages().records:
            if (
                message.id is not None
                and (self._resolve_with(message.to, resolver), message.id)
                not in suppressed
            ):
                result.setdefault(message.to, []).append(message)
        return {key: tuple(value) for key, value in result.items()}

    def peek_unread(self, reader: str) -> tuple[Message, ...]:
        resolver = self._resolver_snapshot()
        resolved = self._resolve_with(reader, resolver)
        index = self.inbox / "index" / f"{resolved}.json"
        start = self._watermark(resolved) if index.exists() else 0
        return self._peek_snapshot(resolved, start, resolver)[0]

    def register_reader(self, reader: str, from_start: bool) -> None:
        resolved = self._resolve(reader)
        resolver = self._resolver_snapshot()
        with (
            file_lock(self._lock(resolved), timeout=30),
            file_lock(self.inbox / ".deliveries.lock", timeout=30),
        ):
            path = self.inbox / "index" / f"{resolved}.json"
            if not path.exists():
                self._write_watermark(
                    resolved, 0 if from_start else self._complete_offset()
                )
            delivered = self._delivered_ids(resolved, resolver)
            if from_start and self._watermark(resolved) == 0:
                self._advance_watermark(
                    resolved, resolver=resolver, delivered_ids=delivered
                )
                self._commit_cursor_locked(resolved, self._watermark(resolved))
            else:
                self._write_delivered(resolved, delivered, resolver)

    def message_ids(self) -> set[str]:
        ids = {
            message.id
            for message in self._read_messages().records
            if message.id is not None
        }
        for line in read_complete_lines(self._messages):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                ids.add(row["id"])
        return ids

    def import_messages(
        self, rows: Iterable[Message | Mapping[str, object]]
    ) -> tuple[Message | Mapping[str, object], ...]:
        rows_to_import = tuple(rows)
        if any(not _row_id(row) for row in rows_to_import):
            raise Invalid("imported messages require an id")
        resolver = self._resolver_snapshot()
        readers = {
            self._resolve_with(str(wire["to"]), resolver)
            for wire in map(_message_wire, rows_to_import)
            if isinstance(wire.get("to"), str)
        }
        imported = []
        with ExitStack() as stack:
            for reader in sorted(readers):
                stack.enter_context(file_lock(self._lock(reader), timeout=30))
            with file_lock(self.inbox / ".messages.lock", timeout=30):
                known = self._cached_message_ids()
                for row in rows_to_import:
                    message_id = _row_id(row)
                    if message_id is None:
                        raise Invalid("imported messages require an id")
                    if message_id in known:
                        continue
                    wire = _message_wire(row)
                    recipient = wire.get("to")
                    if isinstance(recipient, str):
                        self._seed_index(self._resolve_with(recipient, resolver))
                    self._append_message_locked(
                        json.dumps(
                            wire, ensure_ascii=False, separators=(",", ":")
                        ).encode()
                    )
                    known.add(message_id)
                    self._message_ids_cache_size = self._messages.stat().st_size
                    imported.append(row)
        return tuple(imported)

    def reader_position(self, reader: str) -> str | None:
        """Return the last message at the files byte watermark."""
        resolved = self._resolve(reader)
        validate_address(resolved, "reader")
        watermark = self._watermark(resolved)
        raw = self._messages.read_bytes() if self._messages.exists() else b""
        result = None
        for line in io.BytesIO(raw[:watermark]):
            parsed = parse_messages(line).records
            if parsed:
                result = parsed[-1].id
        return result

    def import_reader_position(self, reader: str, message_id: str | None) -> None:
        """Map a message id to the files byte watermark and cursor offset."""
        resolved = self._resolve(reader)
        validate_address(resolved, "reader")
        raw = self._messages.read_bytes() if self._messages.exists() else b""
        position = 0
        found = message_id is None
        if message_id is not None:
            for line in io.BytesIO(raw):
                position += len(line)
                parsed = parse_messages(line).records
                if parsed and parsed[-1].id == message_id:
                    found = True
                    break
        if not found:
            raise Invalid(f"message id `{message_id}` does not exist")
        with file_lock(self._lock(resolved), timeout=30):
            atomic_write(
                self.inbox / "index" / f"{resolved}.json",
                json.dumps({"watermark": position}).encode(),
                mode=0o644,
            )
            atomic_write(
                self.inbox / "cursors" / resolved,
                str(position).encode("ascii"),
                mode=0o644,
            )

    def import_deliveries(self, rows: Iterable[Delivery]) -> None:
        """Replay full-row identities in source order; identical rows collapse."""
        incoming = tuple(rows)
        with file_lock(self.inbox / ".deliveries.lock", timeout=30):
            known = {
                _delivery_identity(row) for row in self._deliveries_read(strict=True)
            }
            unseen = []
            for row in incoming:
                identity = _delivery_identity(row)
                if identity not in known:
                    known.add(identity)
                    unseen.append(row)
            self._append_deliveries_locked(unseen)

    def import_concluded(self, addresses: Iterable[str]) -> None:
        """Union imported addresses into the files concluded state."""
        incoming = set(addresses)
        for address in incoming:
            validate_address(address)
        with file_lock(self.inbox / ".state.lock", timeout=30):
            try:
                state = json.loads(
                    (self.inbox / "state.json").read_text(encoding="utf-8")
                )
            except OSError, ValueError:
                state = {}
            addresses = (
                state.get("concluded_addresses", []) if isinstance(state, dict) else []
            )
            existing = (
                {item for item in addresses if isinstance(item, str)}
                if isinstance(addresses, list)
                else set()
            )
            updated = sorted(existing | incoming)
            atomic_write(
                self.inbox / "state.json",
                json.dumps(
                    {"concluded_addresses": updated}, separators=(",", ":")
                ).encode(),
                mode=0o644,
            )

    def _append_message_locked(self, line: bytes) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        payload = line.rstrip(b"\n") + b"\n"
        if self._messages.exists() and self._messages.stat().st_size:
            with self._messages.open("rb") as stream:
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    payload = b"\n" + payload
        descriptor = os.open(
            self._messages, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644
        )
        try:
            if os.write(descriptor, payload) != len(payload):
                raise OSError("short append to messages log")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def commit_cursor(self, reader: str, cursor: Cursor) -> None:
        resolved = self._resolve(reader)
        try:
            value = int(cursor.value)
        except ValueError:
            raise Invalid("invalid message cursor") from None
        if value < 0 or value > self._complete_offset():
            raise Invalid("message cursor is outside the stream")
        with file_lock(self._lock(resolved), timeout=30):
            path = self.inbox / "cursors" / resolved
            try:
                prior = int(path.read_text())
            except OSError, ValueError:
                prior = 0
            atomic_write(path, str(max(value, prior)).encode("ascii"), mode=0o644)

    def import_cursor(self, reader: str, cursor: Cursor) -> None:
        """Set a mirrored cursor exactly, including a required rewind."""
        resolved = self._resolve(reader)
        try:
            value = int(cursor.value)
        except ValueError:
            raise Invalid("invalid message cursor") from None
        if value < 0 or value > self._complete_offset():
            raise Invalid("message cursor is outside the stream")
        with file_lock(self._lock(resolved), timeout=30):
            atomic_write(
                self.inbox / "cursors" / resolved,
                str(value).encode("ascii"),
                mode=0o644,
            )

    def unread(self, reader: str) -> tuple[Message, ...]:
        resolver = self._resolver_snapshot()
        resolved = self._resolve_with(reader, resolver)
        with file_lock(self._lock(resolved), timeout=30):
            start = self._seed_index(resolved)
            return self._peek_snapshot(resolved, start, resolver)[0]

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
        before_claim: Callable[[], object],
    ) -> tuple[Message, ...]:
        """Mark mirror lag after finding messages and before claiming them."""
        return self._claim_unread(reader, session, via, now, before_claim)

    def _claim_unread(
        self,
        reader: str,
        session: str,
        via: str,
        now: str | None,
        before_claim: Callable[[], object] | None = None,
    ) -> tuple[Message, ...]:
        resolver = self._resolver_snapshot()
        resolved = self._resolve_with(reader, resolver)
        with (
            file_lock(self._lock(resolved), timeout=self.lock_timeout),
            file_lock(self.inbox / ".deliveries.lock", timeout=self.lock_timeout),
        ):
            index = self.inbox / "index" / f"{resolved}.json"
            if before_claim is None:
                start = self._seed_index(resolved)
            else:
                start = self._watermark(resolved) if index.exists() else 0
            events = self._delivered_ids(resolved, resolver)
            messages, claim_end = self._peek_snapshot(
                resolved, start, resolver, delivered_ids=events
            )
            if not messages and before_claim is not None:
                return ()
            if messages and before_claim is not None:
                before_claim()
                if not index.exists():
                    self._write_watermark(resolved, 0)
            at = timestamp(now)
            for message in messages:
                for event in ("delivered", "acked"):
                    self._append_delivery(
                        Delivery(message.id or "", resolved, session, via, event, at)
                    )
                if message.id:
                    events.add(message.id)
            self._advance_watermark(
                resolved,
                limit=claim_end,
                resolver=resolver,
                delivered_ids=events,
            )
            self._commit_cursor_locked(resolved, claim_end)
            return messages

    def _write_delivered(
        self,
        reader: str,
        values: set[str],
        resolver: ReaderResolver | None = None,
    ) -> None:
        try:
            delivery_size = self._deliveries.stat().st_size
        except FileNotFoundError:
            delivery_size = 0
        atomic_write(
            self.inbox / "index" / f"{reader}.delivered.json",
            json.dumps(
                {
                    "delivery_size": delivery_size,
                    "addresses": sorted(
                        (resolver or self._resolver_snapshot()).addresses(reader)
                    ),
                    "ids": sorted(values - {""}),
                }
            ).encode(),
            mode=0o644,
        )

    def _advance_watermark(
        self,
        reader: str,
        *,
        limit: int | None = None,
        resolver: ReaderResolver | None = None,
        delivered_ids: set[str] | None = None,
    ) -> None:
        watermark = self._seed_index(reader)
        resolver = resolver or self._resolver_snapshot()
        addresses = resolver.addresses(reader)
        raw = self._messages.read_bytes() if self._messages.exists() else b""
        complete = raw[: raw.rfind(b"\n") + 1] if raw else b""
        if limit is not None:
            complete = complete[:limit]
        events = (
            delivered_ids
            if delivered_ids is not None
            else self._delivered_ids(reader, resolver)
        )
        position = watermark
        stream = io.BytesIO(complete)
        stream.seek(watermark)
        while line := stream.readline():
            end = position + len(line)
            message = parse_messages(line).records
            if message and message[0].to in addresses and message[0].id not in events:
                break
            position = end
        self._write_watermark(reader, position)
        self._write_delivered(reader, events, resolver)

    def _commit_cursor_locked(self, reader: str, value: int) -> None:
        path = self.inbox / "cursors" / reader
        try:
            prior = int(path.read_text())
        except OSError, ValueError:
            prior = 0
        atomic_write(path, str(max(value, prior)).encode("ascii"), mode=0o644)

    def record_delivery(self, delivery: Delivery) -> DeliveryOutcome:
        resolver = self._resolver_snapshot()
        resolved = self._resolve_with(delivery.reader, resolver)
        with (
            file_lock(self._lock(resolved), timeout=30),
            file_lock(self.inbox / ".deliveries.lock", timeout=30),
        ):
            return self._record(delivery, resolved, resolver)

    def _record(
        self, delivery: Delivery, resolved: str, resolver: ReaderResolver
    ) -> DeliveryOutcome:
        prior = self._deliveries_read()
        if delivery.event == "delivered":
            watermark = self._seed_index(resolved)
            tail = self._tail_messages(watermark)
            tail_ids = {
                message.id
                for message in tail
                if message.to in resolver.addresses(resolved)
            }
            suppressed = {
                item.message_id
                for item in prior
                if self._resolve_with(item.reader, resolver) == resolved
                and item.event in {"delivered", "dropped", "legacy"}
            }
            prior_delivered = any(
                item.message_id == delivery.message_id
                and self._resolve_with(item.reader, resolver) == resolved
                and item.event == "delivered"
                for item in prior
            )
            if prior_delivered:
                return DeliveryOutcome.DUPLICATE
            if delivery.message_id in suppressed:
                return DeliveryOutcome.SKIPPED
            if delivery.message_id not in tail_ids:
                return DeliveryOutcome.SKIPPED
        if delivery.event == "acked":
            validate_message_id(delivery.message_id)
            if not any(
                m.id == delivery.message_id and m.to in resolver.addresses(resolved)
                for m in self._read_messages().records
            ) or not any(
                d.message_id == delivery.message_id
                and self._resolve_with(d.reader, resolver) == resolved
                and d.event == "delivered"
                for d in prior
            ):
                return DeliveryOutcome.SKIPPED
        self._append_delivery(
            Delivery(
                delivery.message_id,
                resolved,
                delivery.session,
                delivery.via,
                delivery.event,
                delivery.at,
                delivery.action_created_at,
                delivery.reason,
            )
        )
        if delivery.event in {"delivered", "dropped", "legacy"}:
            self._advance_watermark(resolved, resolver=resolver)
        return DeliveryOutcome.RECORDED

    def _tail_messages(self, start: int) -> tuple[Message, ...]:
        raw = self._messages.read_bytes() if self._messages.exists() else b""
        complete = raw[: raw.rfind(b"\n") + 1] if raw else b""
        return parse_messages(complete[start:]).records

    def record_relay_event(self, event: RelayEvent) -> DeliveryOutcome:
        resolver = self._resolver_snapshot()
        resolved = self._resolve_with(event.reader, resolver)
        with (
            file_lock(self._lock(resolved), timeout=30),
            file_lock(self.inbox / ".deliveries.lock", timeout=30),
        ):
            existing = self._deliveries_read()
            related = [
                d
                for d in existing
                if d.message_id == event.message_id
                and self._resolve_with(d.reader, resolver) == resolved
            ]
            if event.event in {"pushed", "skipped-busy", "failed", "target-gone"}:
                for item in related:
                    if item.event in {
                        "pushed",
                        "skipped-busy",
                        "failed",
                        "target-gone",
                    } and (
                        not event.action_created_at
                        or not item.action_created_at
                        or item.action_created_at >= event.action_created_at
                    ):
                        return DeliveryOutcome.DUPLICATE
            if event.event == "delivered" and any(
                d.event == "delivered" for d in related
            ):
                return DeliveryOutcome.DUPLICATE
            delivery = Delivery(
                event.message_id,
                resolved,
                event.session,
                event.via,
                event.event,
                event.now,
                event.action_created_at,
                event.reason,
                event.details,
            )
            self._append_delivery(delivery)
            if event.event in {"delivered", "dropped", "legacy"}:
                self._advance_watermark(resolved, resolver=resolver)
            return DeliveryOutcome.RECORDED

    def record_relay_events(self, events: Iterable[RelayEvent]) -> None:
        resolver = self._resolver_snapshot()
        deliveries = tuple(
            Delivery(
                event.message_id,
                self._resolve_with(event.reader, resolver),
                event.session,
                event.via,
                event.event,
                event.now,
                event.action_created_at,
                event.reason,
                event.details,
            )
            for event in events
        )
        if not deliveries:
            return
        with file_lock(self.inbox / ".deliveries.lock", timeout=30):
            self._append_deliveries_locked(deliveries)

    def ack(self, reader: str, message_id: str, *, now: str | None = None) -> bool:
        validate_message_id(message_id)
        resolver = self._resolver_snapshot()
        resolved = self._resolve_with(reader, resolver)
        with (
            file_lock(self._lock(resolved), timeout=30),
            file_lock(self.inbox / ".deliveries.lock", timeout=30),
        ):
            if not any(
                m.id == message_id and m.to in resolver.addresses(resolved)
                for m in self._read_messages().records
            ):
                raise NotFound("message does not exist for this reader")
            existing = self._deliveries_read()
            if not any(
                d.message_id == message_id
                and self._resolve_with(d.reader, resolver) == resolved
                and d.event == "delivered"
                for d in existing
            ):
                raise Invalid(
                    "message must be delivered to this reader before it can be acked"
                )
            self._append_delivery(
                Delivery(message_id, resolved, "", "cli", "acked", timestamp(now))
            )
            return True

    def concluded_addresses(self) -> set[str]:
        result = set()
        for path in (self.inbox / "state.json", self.inbox / "relay" / "state.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except OSError, ValueError:
                continue
            addresses = (
                value.get("concluded_addresses", []) if isinstance(value, dict) else []
            )
            if isinstance(addresses, list):
                result.update(item for item in addresses if isinstance(item, str))
        return result

    def mark_concluded(self, address: str) -> None:
        validate_address(address)
        path = self.inbox / "state.json"
        with file_lock(self.inbox / ".state.lock", timeout=30):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except OSError, ValueError:
                value = {}
            addresses = (
                value.get("concluded_addresses", []) if isinstance(value, dict) else []
            )
            if not isinstance(addresses, list):
                addresses = []
            updated = sorted(
                {item for item in addresses if isinstance(item, str)} | {address}
            )
            atomic_write(
                path,
                json.dumps(
                    {"concluded_addresses": updated}, separators=(",", ":")
                ).encode(),
                mode=0o644,
            )

    def status(self) -> MessageStatus:
        acked = tuple(
            sorted(
                {d.message_id for d in self._deliveries_read() if d.event == "acked"}
            )
        )
        from varde_data.backends.files.messages_status import below_watermark

        return MessageStatus(
            sum(len(v) for v in self.pending_by_address().values()),
            acked,
            {"below_watermark": below_watermark(self.inbox)},
        )

    def version(self) -> Version:
        indexes = self.inbox / "index"
        cursors = self.inbox / "cursors"
        return files_version(
            (
                self._messages,
                self._deliveries,
                self.inbox / "state.json",
                indexes,
                cursors,
            ),
        )

    def read_note(self, ref: NoteRef) -> str:
        try:
            return Path(str(ref)).read_text(encoding="utf-8")
        except OSError:
            raise NotFound(f"message note {ref!r} not found") from None
