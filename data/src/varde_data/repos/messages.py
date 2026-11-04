"""Backend-neutral message repository API and shared message parsing."""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Protocol

from varde_data.errors import Invalid
from varde_data.records.messages import (
    Delivery,
    DeliveryOutcome,
    Message,
    MessageStatus,
    NewMessage,
    NoteRef,
    ReadResult,
    RelayEvent,
)
from varde_data.version import Cursor, Version

MESSAGE_KINDS = (
    "blocked",
    "needs-user",
    "done",
    "info",
    "info-failure",
    "stale",
    "merge-ready",
)
_ADDRESS = re.compile(r"[A-Za-z0-9._-]+(?::[A-Za-z0-9._-]+)?\Z", re.ASCII)
_MESSAGE_ID = re.compile(r"m-[0-9a-f]{8}\Z")
MAX_TEXT_CHARS = 300
MAX_LINE_BYTES = 1_000


class MessageRepository(Protocol):
    def append(self, message: NewMessage) -> Message: ...

    def head(self) -> Cursor: ...

    def read_since(self, cursor: Cursor) -> ReadResult: ...

    def read_all(self) -> ReadResult: ...

    def deliveries(self) -> tuple[Delivery, ...]: ...

    def status_events(self) -> tuple[Mapping[str, object], ...]: ...

    def pending_by_address(self) -> Mapping[str, tuple[Message, ...]]: ...

    def peek_unread(self, reader: str) -> tuple[Message, ...]: ...

    def register_reader(self, reader: str, from_start: bool) -> None: ...

    def message_ids(self) -> set[str]: ...

    def import_messages(
        self, rows: Iterable[Message | Mapping[str, object]]
    ) -> tuple[Message | Mapping[str, object], ...]: ...

    def reader_position(self, reader: str) -> str | None:
        """Return the last message id, or None at both start and when unseen.

        Importing None places the reader at the beginning; callers that need to
        distinguish unseen from start must track that separately.
        """
        ...

    def import_reader_position(self, reader: str, message_id: str | None) -> None: ...

    def import_deliveries(self, rows: Iterable[Delivery]) -> None:
        """Replay delivery history idempotently using the full row as identity.

        Identical rows collapse; source ordinal is not part of row identity.
        """
        ...

    def import_concluded(self, addresses: Iterable[str]) -> None: ...

    def commit_cursor(self, reader: str, cursor: Cursor) -> None: ...

    def import_cursor(self, reader: str, cursor: Cursor) -> None: ...

    def claim_unread(
        self, reader: str, session: str, via: str, now: str | None = None
    ) -> tuple[Message, ...]: ...

    def unread(self, reader: str) -> tuple[Message, ...]: ...

    def record_delivery(self, delivery: Delivery) -> DeliveryOutcome:
        """Skip unpaired ack events; malformed IDs and direct ``ack`` raise Invalid."""
        ...

    def record_relay_event(self, event: RelayEvent) -> DeliveryOutcome: ...

    def ack(self, reader: str, message_id: str, *, now: str | None = None) -> bool: ...

    def concluded_addresses(self) -> set[str]: ...

    def mark_concluded(self, address: str) -> None:
        """Advance version for every write, even when the address already exists."""
        ...

    def status(self) -> MessageStatus: ...

    def version(self) -> Version: ...

    def read_note(self, ref: NoteRef) -> str: ...


class StaticReaderResolver:
    """A minimal resolver useful for backends without a slot registry."""

    def resolve(self, name: str) -> str:
        return name

    def addresses(self, slot: str) -> set[str]:
        return {slot}


def validate_message(message: NewMessage) -> None:
    """Validate the stable message write contract."""
    validate_address(message.from_, "--from")
    validate_address(message.to, "--to")
    if message.reply_to is not None:
        validate_message_id(message.reply_to)
    if message.kind not in MESSAGE_KINDS:
        raise Invalid(
            f"unknown message kind `{message.kind}`; allowed kinds are "
            + ", ".join(MESSAGE_KINDS)
        )
    if not message.text:
        raise Invalid("message text must not be empty")
    if "\n" in message.text or "\r" in message.text:
        raise Invalid("message text must be one line without newlines")
    if len(message.text) > MAX_TEXT_CHARS:
        raise Invalid(
            f"message text is {len(message.text)} characters; {MAX_TEXT_CHARS} "
            "characters is the limit; use --notes <path>"
        )
    encoded = (
        json.dumps(
            _message_dict(message), ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        + b"\n"
    )
    if len(encoded) > MAX_LINE_BYTES:
        raise Invalid(
            f"message encodes to {len(encoded)} bytes; the encoded line limit is "
            f"{MAX_LINE_BYTES} bytes; use --notes <path>"
        )


def validate_address(address: str, flag: str = "address") -> None:
    if not address:
        raise Invalid(f"{flag} must not be empty")
    if not _ADDRESS.fullmatch(address):
        raise Invalid(
            f"{flag} `{address}` must be one word of letters, digits, `.`, `_` or `-`, "
            "with an optional `:qualifier`"
        )


def validate_message_id(message_id: str) -> None:
    if not _MESSAGE_ID.fullmatch(message_id):
        raise Invalid("message id must match m-[0-9a-f]{8}")


def parse_messages(
    data: bytes, *, start_offset: int = 0, start_line: int = 0
) -> ReadResult:
    """Parse LF-delimited rows without treating a legacy lone CR as a separator."""
    records: list[Message] = []
    skipped: list[str] = []
    offset = start_offset
    stream = io.BytesIO(data)
    line_number = start_line
    while line := stream.readline():
        if not line.endswith(b"\n"):
            break
        line_number += 1
        raw = line.rstrip(b"\r\n")
        try:
            value = json.loads(raw)
            message = _message_from_value(value)
            if message.id is None:
                legacy_id = (
                    "m-" + hashlib.sha256(str(offset).encode() + raw).hexdigest()[:8]
                )
                message = Message(
                    message.ts,
                    message.from_,
                    message.to,
                    message.kind,
                    message.text,
                    message.notes,
                    legacy_id,
                    legacy_id,
                    message.reply_to,
                )
            records.append(message)
        except (ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
            skipped.append(f"line {line_number}: {exc}")
        offset += len(line)
    return ReadResult(tuple(records), tuple(skipped))


def timestamp(value: str | None = None) -> str:
    if value is not None:
        return value
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _message_dict(message: NewMessage) -> dict[str, str]:
    return {
        "ts": message.ts or timestamp(),
        "from": message.from_,
        "to": message.to,
        "kind": message.kind,
        "text": message.text,
        **({"notes": message.notes} if message.notes is not None else {}),
        **({"reply_to": message.reply_to} if message.reply_to is not None else {}),
        "id": "m-00000000",
    }


def _message_from_value(value: object) -> Message:
    if not isinstance(value, dict):
        raise TypeError("message must be an object")
    fields = (value["ts"], value["from"], value["to"], value["kind"], value["text"])
    notes, message_id = value.get("notes"), value.get("id")
    reply_to = value.get("reply_to", value.get("in_reply_to"))
    if not all(isinstance(item, str) for item in fields):
        raise ValueError("message fields must be strings")
    if notes is not None and not isinstance(notes, str):
        raise ValueError("message notes must be a string")
    if message_id is not None and not isinstance(message_id, str):
        raise ValueError("message id must be a string")
    if reply_to is not None and not isinstance(reply_to, str):
        raise ValueError("message reply_to must be a string")
    return Message(*fields, notes, message_id, None, reply_to)
