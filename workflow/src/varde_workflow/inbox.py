"""Small, dependency-free helpers used by app hook dispatch."""

from __future__ import annotations

import json
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from queue import Queue
from typing import TypeVar

from varde_workflow.relay_wake import touch as touch_relay_wake

SETUP_WARNING = (
    "Varde will not work as designed until its instruction block is installed: "
    "agents will not "
    "delegate as designed or use captured command output. Install it with `varde setup "
    "instructions install --target <file>`. Use one canonical `AGENTS.md` "
    "symlinked into each harness."
)
_START_MARKER = b"<!-- varde:start -->"
_END_MARKER = b"<!-- varde:end -->"
MAX_TEXT_CHARS = 300
KINDS = (
    "blocked",
    "needs-user",
    "done",
    "info",
    "info-failure",
    "stale",
    "merge-ready",
)


@dataclass(frozen=True)
class Message:
    ts: str
    from_: str
    to: str
    kind: str
    text: str
    notes: str | None = None
    id: str | None = None
    reply_to: str | None = None

    @property
    def from_address(self) -> str:
        return self.from_

    def line(self) -> str:
        suffix = f" (notes: {self.notes})" if self.notes is not None else ""
        return f"{self.from_} {self.kind}: {self.text}{suffix}"

    def to_dict(self) -> dict[str, str]:
        result = {
            "ts": self.ts,
            "from": self.from_,
            "to": self.to,
            "kind": self.kind,
            "text": self.text,
        }
        if self.notes is not None:
            result["notes"] = self.notes
        if self.id is not None:
            result["id"] = self.id
        if self.reply_to is not None:
            result["reply_to"] = self.reply_to
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, value: object) -> Message:
        if not isinstance(value, dict):
            raise ValueError("message must be an object")
        fields = (value["ts"], value["from"], value["to"], value["kind"], value["text"])
        notes = value.get("notes")
        message_id = value.get("id")
        if (
            not all(isinstance(field, str) for field in fields)
            or (notes is not None and not isinstance(notes, str))
            or (message_id is not None and not isinstance(message_id, str))
        ):
            raise ValueError("message fields must be strings")
        reply_to = value.get("reply_to", value.get("in_reply_to"))
        if reply_to is not None and not isinstance(reply_to, str):
            raise ValueError("message reply_to must be a string")
        return cls(*fields, notes, message_id, reply_to)


class WithinError(Exception):
    """The bounded hook work timed out or raised an exception."""

    TIMED_OUT = "timed_out"
    PANICKED = "panicked"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


T = TypeVar("T")


def within[T](timeout: float, work: Callable[[], T]) -> T:
    """Run work on a daemon thread, raising WithinError on timeout or failure."""
    result: Queue[tuple[bool, object]] = Queue(maxsize=1)

    def run() -> None:
        try:
            result.put((True, work()))
        except BaseException as exc:
            result.put((False, exc))

    threading.Thread(target=run, daemon=True).start()
    try:
        succeeded, value = result.get(timeout=max(0.0, timeout))
    except Exception as exc:
        from queue import Empty

        if isinstance(exc, Empty):
            raise WithinError(WithinError.TIMED_OUT) from None
        raise
    if succeeded:
        return value  # type: ignore[return-value]
    raise WithinError(WithinError.PANICKED) from value  # type: ignore[misc]


def has_managed_block(path: str | Path) -> bool:
    try:
        content = Path(path).read_bytes()
    except OSError:
        return False
    start = content.find(_START_MARKER)
    if start < 0:
        return False
    return content.find(_END_MARKER, start + len(_START_MARKER)) >= 0


def owned_plan_id(path: str | Path, owner: str) -> str | None:
    """Return a plan's explicit or directory-derived ID when its owner matches."""
    try:
        content = Path(path).read_bytes()
        from varde_learn.knowledge.frontmatter import parse

        mapping, _ = parse(content)
    except OSError, ValueError:
        return None
    artifact_type = mapping.get("artifact_type", mapping.get("type", "plan"))
    if artifact_type != "plan" or mapping.get("owner") != owner:
        return None
    if isinstance(mapping.get("id"), str):
        return mapping["id"]
    file_path = Path(path)
    if file_path.name == "plan.md":
        return file_path.parent.name or "plan"
    return file_path.stem or "artifact"


def _repository(working: str | Path):
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    return open_data(Path(working), load_data_config()).messages


def _inbox_dir(working: str | Path) -> Path:
    """Compatibility path helper for workflow readers not yet migrated."""
    return Path(working) / ".cache" / "inbox"


def _valid_address(address: str, flag: str) -> None:
    from varde_data.repos.messages import validate_address

    validate_address(address, flag)


def _from_record(record) -> Message:
    return Message(
        record.ts,
        record.from_,
        record.to,
        record.kind,
        record.text,
        record.notes,
        record.id,
        record.reply_to,
    )


def seed_reader_index(working: str | Path, reader: str) -> None:
    _repository(working).register_reader(reader, from_start=False)


def read_all(working: str | Path) -> list[Message]:
    return [_from_record(item) for item in _repository(working).read_all().records]


def append_message(  # noqa: PLR0913
    from_address: str,
    to: str,
    kind: str,
    text: str,
    notes: str | Path | None = None,
    *,
    working: str | Path | None = None,
    now: datetime | None = None,
    reply_to: str | None = None,
) -> Message:
    """Validate and append one message to the inbox."""
    from varde_data.errors import Invalid
    from varde_data.records.messages import NewMessage

    if working is None:
        from varde_learn.knowledge.memory import MemoryPaths, find_root

        cwd = Path.cwd()
        root = MemoryPaths.resolve(find_root(cwd) or cwd).working.path
    else:
        root = Path(working)
    stamp = (
        (now or datetime.now(UTC))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    try:
        stored = _repository(root).append(
            NewMessage(
                from_address,
                to,
                kind,
                text,
                str(notes) if notes is not None else None,
                stamp,
                reply_to,
            )
        )
    except Invalid as exc:
        raise ValueError(str(exc)) from None
    touch_relay_wake(root)
    return _from_record(stored)


def append_event_message(
    working: str | Path,
    from_address: str,
    to: str,
    kind: str,
    text: str,
    notes: str | Path | None = None,
) -> Message:
    clean = "".join(
        character for character in text if unicodedata.category(character) != "Cc"
    )
    if len(clean) > MAX_TEXT_CHARS:
        clean = clean[: MAX_TEXT_CHARS - 1] + "…"
    return append_message(from_address, to, kind, clean, notes, working=working)


def pending_for_readers(working: str | Path) -> dict[str, list[Message]]:
    """Return undelivered messages grouped by every addressed reader."""
    return {
        address: [_from_record(item) for item in messages]
        for address, messages in _repository(working).pending_by_address().items()
    }


def read_unread(working: str | Path, reader: str) -> tuple[list[Message], int | None]:
    repository = _repository(working)
    return [_from_record(item) for item in repository.unread(reader)], int(
        repository.head().value
    )


def delivery_events(working: str | Path) -> list[dict[str, str]]:
    return [
        {
            "message_id": delivery.message_id,
            "reader": delivery.reader,
            "session": delivery.session,
            "via": delivery.via,
            "event": delivery.event,
            "at": delivery.at,
            **(
                {"action_created_at": delivery.action_created_at}
                if delivery.action_created_at is not None
                else {}
            ),
            **({"reason": delivery.reason} if delivery.reason is not None else {}),
            **{
                key: value
                for key, value in delivery.details.items()
                if key
                not in {
                    "message_id",
                    "reader",
                    "session",
                    "via",
                    "event",
                    "at",
                    "action_created_at",
                    "reason",
                }
            },
        }
        for delivery in _repository(working).deliveries()
    ]


def record_delivery(  # noqa: PLR0913
    working: str | Path,
    message_id: str,
    reader: str,
    event: str = "delivered",
    *,
    session: str | None = None,
    via: str = "cli",
    now: str | None = None,
    reason: str | None = None,
) -> None:
    from varde_data.errors import DataError
    from varde_data.records.messages import Delivery, DeliveryOutcome

    repository = _repository(working)
    duplicate = False
    try:
        if event == "acked":
            recorded = repository.ack(
                reader,
                message_id,
                now=now or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
        else:
            outcome = repository.record_delivery(
                Delivery(
                    message_id,
                    reader,
                    session or "",
                    via,
                    event,
                    now or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    reason=reason,
                )
            )
            recorded = outcome is DeliveryOutcome.RECORDED
            duplicate = outcome is DeliveryOutcome.DUPLICATE
    except DataError as exc:
        raise ValueError(str(exc)) from None
    if recorded:
        touch_relay_wake(working)
    if (
        event == "delivered"
        and via in {"hook", "receipt", "read"}
        and (recorded or duplicate)
    ):
        _clear_wake_gone(
            working, reader, datetime.fromisoformat(now) if now else datetime.now(UTC)
        )


def record_relay_event(  # noqa: PLR0913
    working: str | Path,
    message_id: str,
    reader: str,
    event: str,
    *,
    now: datetime,
    session: str = "",
    via: str = "relay",
    **details: str,
) -> bool:
    from varde_data.records.messages import DeliveryOutcome, RelayEvent

    result = _repository(working).record_relay_event(
        RelayEvent(
            message_id,
            reader,
            event,
            now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            session,
            via,
            details.get("action_created_at"),
            details.get("reason"),
            {
                key: value
                for key, value in details.items()
                if key
                not in {
                    "message_id",
                    "reader",
                    "session",
                    "via",
                    "event",
                    "now",
                    "action_created_at",
                    "reason",
                }
            },
        )
    )
    if result is DeliveryOutcome.RECORDED:
        touch_relay_wake(working)
    if (
        event == "delivered"
        and via in {"hook", "receipt", "read"}
        and result in {DeliveryOutcome.RECORDED, DeliveryOutcome.DUPLICATE}
    ):
        _clear_wake_gone(working, reader, now)
    return result is DeliveryOutcome.RECORDED


def _clear_wake_gone(working: str | Path, reader: str, now: datetime) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    open_data(Path(working), load_data_config()).addresses.clear_wake_gone(reader, now)


def unread(working: str | Path, reader: str) -> list[Message]:
    return [_from_record(item) for item in _repository(working).unread(reader)]


def claim_unread(
    working: str | Path,
    reader: str,
    session: str,
    via: str,
    *,
    now: str | None = None,
) -> list[Message]:
    """Atomically claim and acknowledge unread messages for one reader."""
    records = _repository(working).claim_unread(
        reader,
        session,
        via,
        now or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    if records:
        touch_relay_wake(working)
    return [_from_record(item) for item in records]


def commit_cursor(working: str | Path, reader: str, offset: int) -> None:
    from varde_data.version import Cursor

    _repository(working).commit_cursor(reader, Cursor(str(offset)))
