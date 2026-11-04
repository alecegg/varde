"""In-memory message repository used by contracts and ephemeral callers."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterable, Mapping

from varde_data.backends.memory.workitems import MemoryWorkItems
from varde_data.errors import Invalid, NotFound
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


def _row_id(row: Message | Mapping[str, object]) -> str | None:
    if isinstance(row, Message):
        return row.id
    message_id = row.get("id")
    return message_id if isinstance(message_id, str) else None


class MemoryMessages:
    def __init__(
        self,
        resolver: ReaderResolver | None = None,
        notes: Mapping[NoteRef, str] | None = None,
        *,
        state_concluded: Iterable[str] = (),
        relay_concluded: Iterable[str] = (),
    ) -> None:
        self._resolver = resolver or StaticReaderResolver()
        self._notes = dict(notes or {})
        self._messages: list[Message] = []
        self._raw_imports: dict[str, Mapping[str, object]] = {}
        self._deliveries: list[Delivery] = []
        self._reader_cursors: dict[str, int] = {}
        self._state_concluded = set(state_concluded)
        self._relay_concluded = set(relay_concluded)
        self._revision = 0
        self._lock = threading.RLock()

    def append(self, message: NewMessage) -> Message:
        validate_message(message)
        with self._lock:
            reader = self._resolve(message.to)
            self._reader_cursors.setdefault(reader, len(self._messages))
            known = self.message_ids()
            while True:
                message_id = "m-" + uuid.uuid4().hex[:8]
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
            self._messages.append(stored)
            self._revision += 1
        return stored

    def head(self) -> Cursor:
        return self._cursor(len(self._messages))

    def read_since(self, cursor: Cursor) -> ReadResult:
        start = self._cursor_position(cursor)
        if start > len(self._messages):
            raise Invalid("message cursor is outside the stream")
        return ReadResult(tuple(self._messages[start:]))

    def read_all(self) -> ReadResult:
        return ReadResult(tuple(self._messages))

    def deliveries(self) -> tuple[Delivery, ...]:
        return tuple(self._deliveries)

    def status_events(self) -> tuple[Mapping[str, object], ...]:
        return ()

    def pending_by_address(self) -> Mapping[str, tuple[Message, ...]]:
        result: dict[str, list[Message]] = {}
        suppressed = {
            (self._resolve(delivery.reader), delivery.message_id)
            for delivery in self._deliveries
            if delivery.event in {"delivered", "dropped", "legacy"}
        }
        for message in self._messages:
            resolved = self._resolve(message.to)
            if message.id is not None and (resolved, message.id) not in suppressed:
                result.setdefault(message.to, []).append(message)
        return {address: tuple(messages) for address, messages in result.items()}

    def peek_unread(self, reader: str) -> tuple[Message, ...]:
        resolved = self._resolve(reader)
        return self._peek_unread_for(resolved)

    def register_reader(self, reader: str, from_start: bool) -> None:
        resolved = self._resolve(reader)
        with self._lock:
            if resolved in self._reader_cursors:
                return
            self._reader_cursors[resolved] = 0 if from_start else len(self._messages)
            self._revision += 1

    def message_ids(self) -> set[str]:
        return {message.id for message in self._messages if message.id} | set(
            self._raw_imports
        )

    def import_messages(
        self, rows: Iterable[Message | Mapping[str, object]]
    ) -> tuple[Message | Mapping[str, object], ...]:
        rows_to_import = tuple(rows)
        if any(not _row_id(row) for row in rows_to_import):
            raise Invalid("imported messages require an id")
        with self._lock:
            known_ids = self.message_ids()
            imported_rows: list[Message | Mapping[str, object]] = []
            for row in rows_to_import:
                message_id = _row_id(row)
                if message_id is None:
                    raise Invalid("imported messages require an id")
                if message_id in known_ids:
                    continue
                known_ids.add(message_id)
                imported_rows.append(row)
                if isinstance(row, Message):
                    reader = self._resolve(row.to)
                    if reader not in self._reader_cursors:
                        self._reader_cursors[reader] = len(self._messages)
                    self._messages.append(row)
                else:
                    self._raw_imports[message_id] = dict(row)
                    try:
                        parsed = parse_messages(
                            json.dumps(dict(row), separators=(",", ":")).encode()
                            + b"\n"
                        )
                    except TypeError, ValueError:
                        parsed = None
                    if parsed and parsed.records:
                        reader = self._resolve(parsed.records[0].to)
                        if reader not in self._reader_cursors:
                            self._reader_cursors[reader] = len(self._messages)
                        self._messages.append(parsed.records[0])
            imported = tuple(imported_rows)
            if imported:
                self._revision += 1
        return imported

    def reader_position(self, reader: str) -> str | None:
        """Return the message at the in-memory reader's integer position."""
        validate_address(reader, "reader")
        position = self._reader_cursors.get(reader, 0)
        if position <= 0 or position > len(self._messages):
            return None
        return self._messages[position - 1].id

    def import_reader_position(self, reader: str, message_id: str | None) -> None:
        """Map an id to the in-memory integer offset without resolving the reader."""
        validate_address(reader, "reader")
        position = 0
        if message_id is not None:
            for index, message in enumerate(self._messages, start=1):
                if message.id == message_id:
                    position = index
                    break
            else:
                raise Invalid(f"message id `{message_id}` does not exist")
        with self._lock:
            self._reader_cursors[reader] = position
            self._revision += 1

    def import_deliveries(self, rows: Iterable[Delivery]) -> None:
        """Replay full-row identities; identical rows collapse, names stay verbatim."""
        with self._lock:
            for row in rows:
                if row not in self._deliveries:
                    self._deliveries.append(row)
                    self._revision += 1

    def import_concluded(self, addresses: Iterable[str]) -> None:
        """Union imported addresses into concluded state."""
        incoming = set(addresses)
        for address in incoming:
            validate_address(address)
        with self._lock:
            added = incoming - (self._state_concluded | self._relay_concluded)
            if added:
                self._state_concluded.update(added)
                self._revision += 1

    def commit_cursor(self, reader: str, cursor: Cursor) -> None:
        resolved = self._resolve(reader)
        position = self._cursor_position(cursor)
        with self._lock:
            if position > len(self._messages):
                raise Invalid("message cursor is outside the stream")
            self._reader_cursors[resolved] = position
            self._revision += 1

    def import_cursor(self, reader: str, cursor: Cursor) -> None:
        """Set a mirrored cursor exactly, including a required rewind."""
        self.commit_cursor(reader, cursor)

    def unread(self, reader: str) -> tuple[Message, ...]:
        resolved = self._resolve(reader)
        with self._lock:
            if resolved not in self._reader_cursors:
                self._reader_cursors[resolved] = len(self._messages)
                self._revision += 1
            return self._peek_unread_for(resolved)

    def claim_unread(
        self, reader: str, session: str, via: str, now: str | None = None
    ) -> tuple[Message, ...]:
        resolved = self._resolve(reader)
        with self._lock:
            if resolved not in self._reader_cursors:
                self._reader_cursors[resolved] = len(self._messages)
                self._revision += 1
            messages = self._peek_unread_for(resolved)
            at = timestamp(now)
            for message in messages:
                self._deliveries.append(
                    Delivery(message.id or "", resolved, session, via, "delivered", at)
                )
                self._deliveries.append(
                    Delivery(message.id or "", resolved, session, via, "acked", at)
                )
            if messages:
                self._reader_cursors[resolved] = len(self._messages)
                self._revision += 1
            return messages

    def record_delivery(self, delivery: Delivery) -> DeliveryOutcome:
        return self._record_delivery(delivery)

    def record_relay_event(self, event: RelayEvent) -> DeliveryOutcome:
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
        resolved = self._resolve(event.reader)
        with self._lock:
            if event.event in {"pushed", "skipped-busy", "failed", "target-gone"}:
                old_events = (
                    item
                    for item in self._deliveries
                    if item.message_id == event.message_id
                    and self._resolve(item.reader) == resolved
                    and item.event
                    in {"pushed", "skipped-busy", "failed", "target-gone"}
                )
                for old in old_events:
                    if (
                        event.action_created_at is None
                        or old.action_created_at is None
                        or old.action_created_at >= event.action_created_at
                    ):
                        return DeliveryOutcome.DUPLICATE
            if event.event == "delivered":
                if any(
                    item.message_id == event.message_id
                    and self._resolve(item.reader) == resolved
                    and item.event == "delivered"
                    for item in self._deliveries
                ):
                    return DeliveryOutcome.DUPLICATE
                self._write_delivery(delivery, resolved)
                return DeliveryOutcome.RECORDED
            return self._store_delivery(delivery, resolved)

    def ack(self, reader: str, message_id: str, *, now: str | None = None) -> bool:
        validate_message_id(message_id)
        resolved = self._resolve(reader)
        with self._lock:
            message = next(
                (item for item in self._messages if item.id == message_id), None
            )
            if message is None or message.to not in self._resolver.addresses(resolved):
                raise NotFound("message does not exist for this reader")
            if any(
                item.message_id == message_id
                and self._resolve(item.reader) == resolved
                and item.event == "acked"
                for item in self._deliveries
            ):
                return False
            if not any(
                item.message_id == message_id
                and self._resolve(item.reader) == resolved
                and item.event == "delivered"
                for item in self._deliveries
            ):
                raise Invalid(
                    "message must be delivered to this reader before it can be acked"
                )
            self._deliveries.append(
                Delivery(message_id, resolved, "", "cli", "acked", timestamp(now))
            )
            self._revision += 1
            return True

    def concluded_addresses(self) -> set[str]:
        return set(self._state_concluded | self._relay_concluded)

    def mark_concluded(self, address: str) -> None:
        validate_address(address)
        with self._lock:
            self._state_concluded.add(address)
            self._revision += 1

    def status(self) -> MessageStatus:
        acked = tuple(
            sorted(
                {item.message_id for item in self._deliveries if item.event == "acked"}
            )
        )
        pending = self.pending_by_address()
        return MessageStatus(
            lag=sum(len(items) for items in pending.values()), acked=acked
        )

    def version(self) -> Version:
        return Version(self._revision)

    def read_note(self, ref: NoteRef) -> str:
        try:
            return self._notes[ref]
        except KeyError:
            raise NotFound(f"message note {ref!r} not found") from None

    def _resolve(self, reader: str) -> str:
        validate_address(reader, "reader")
        return self._resolver.resolve(reader)

    def _peek_unread_for(self, reader: str) -> tuple[Message, ...]:
        addresses = self._resolver.addresses(reader)
        start = self._reader_cursors.get(reader, 0)
        if len(addresses) > 1:
            start = 0
        suppressed = {
            delivery.message_id
            for delivery in self._deliveries
            if self._resolve(delivery.reader) == reader
            and delivery.event in {"delivered", "dropped", "legacy"}
        }
        return tuple(
            message
            for message in self._messages[start:]
            if message.to in addresses and message.id not in suppressed
        )

    def _record_delivery(self, delivery: Delivery) -> DeliveryOutcome:
        resolved = self._resolve(delivery.reader)
        with self._lock:
            return self._store_delivery(delivery, resolved)

    def _store_delivery(self, delivery: Delivery, resolved: str) -> DeliveryOutcome:
        matching_message = next(
            (
                message
                for message in self._messages
                if message.id == delivery.message_id
            ),
            None,
        )
        if delivery.event == "delivered":
            if any(
                item.message_id == delivery.message_id
                and self._resolve(item.reader) == resolved
                and item.event == "delivered"
                for item in self._deliveries
            ):
                return DeliveryOutcome.DUPLICATE
            if (
                matching_message is None
                or matching_message.to not in self._resolver.addresses(resolved)
            ):
                return DeliveryOutcome.SKIPPED
        if delivery.event == "acked":
            validate_message_id(delivery.message_id)
            delivered = any(
                item.message_id == delivery.message_id
                and self._resolve(item.reader) == resolved
                and item.event == "delivered"
                for item in self._deliveries
            )
            if (
                matching_message is None
                or matching_message.to not in self._resolver.addresses(resolved)
                or not delivered
            ):
                return DeliveryOutcome.SKIPPED
        self._write_delivery(delivery, resolved)
        return DeliveryOutcome.RECORDED

    def _write_delivery(self, delivery: Delivery, resolved: str) -> None:
        self._deliveries.append(
            Delivery(
                delivery.message_id,
                resolved,
                delivery.session,
                delivery.via,
                delivery.event,
                delivery.at,
                delivery.action_created_at,
                delivery.reason,
                delivery.details,
            )
        )
        self._revision += 1

    @staticmethod
    def _cursor(position: int) -> Cursor:
        return Cursor(f"{position:020d}")

    @staticmethod
    def _cursor_position(cursor: Cursor) -> int:
        try:
            position = int(cursor.value)
        except ValueError:
            raise Invalid("invalid message cursor") from None
        if position < 0:
            raise Invalid("message cursor is outside the stream")
        return position


__all__ = ["MemoryMessages", "MemoryWorkItems"]
