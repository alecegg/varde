"""Message domain records shared by all storage backends."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import NewType, Protocol


@dataclass(frozen=True)
class NewMessage:
    from_: str
    to: str
    kind: str
    text: str
    notes: str | None = None
    ts: str | None = None
    reply_to: str | None = None


@dataclass(frozen=True)
class Message:
    ts: str
    from_: str
    to: str
    kind: str
    text: str
    notes: str | None = None
    id: str | None = None
    legacy_id: str | None = None
    reply_to: str | None = None

    @property
    def from_address(self) -> str:
        return self.from_


@dataclass(frozen=True)
class Delivery:
    message_id: str
    reader: str
    session: str
    via: str
    event: str
    at: str
    action_created_at: str | None = None
    reason: str | None = None
    details: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RelayEvent:
    message_id: str
    reader: str
    event: str
    now: str
    session: str = ""
    via: str = "relay"
    action_created_at: str | None = None
    reason: str | None = None
    details: Mapping[str, str] = field(default_factory=dict)


class DeliveryOutcome(Enum):
    RECORDED = "recorded"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class MessageStatus:
    """Backend-neutral message counts with optional backend diagnostics.

    Storage-specific status detail, such as file watermarks or stray stores,
    belongs in ``diagnostics`` and may be empty for any backend.
    """

    lag: int = 0
    acked: tuple[str, ...] = ()
    diagnostics: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ReadResult:
    records: tuple[Message, ...]
    skipped: tuple[str, ...] = ()


NoteRef = NewType("NoteRef", str)


class ReaderResolver(Protocol):
    """Resolve aliases to readers and enumerate addresses owned by a reader."""

    def resolve(self, name: str) -> str: ...

    def addresses(self, slot: str) -> set[str]: ...
