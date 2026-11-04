"""Friction event and folded-state records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ItemAdded:
    title: str
    source: str
    repo_root: str | None = None
    target: str | None = None
    tags: list[str] | None = None


@dataclass(frozen=True)
class ItemTagsChanged:
    item: str
    tags: list[str]


@dataclass(frozen=True)
class OccurrenceAppended:
    item: str
    at: str
    cwd: str
    evidence: str
    repo_root: str | None = None
    head_sha: str | None = None
    cost: str | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class StatusChanged:
    item: str
    at: str
    from_: str
    to: str
    reason: str


@dataclass(frozen=True)
class AdoptionRecorded:
    at: str
    summary: str
    files: list[str]
    items: list[str]
    commit_sha: str | None = None
    eval_before: str | None = None
    eval_after: str | None = None


type EventBody = (
    ItemAdded | ItemTagsChanged | OccurrenceAppended | StatusChanged | AdoptionRecorded
)


@dataclass(frozen=True)
class Event:
    v: int
    id: str
    ts: str
    kind: str
    body: EventBody
    repo: str | None = None
    redacted: int = 0

    @classmethod
    def at(
        cls,
        ts: str,
        repo: str | None,
        body: EventBody,
        *,
        pid: int | None = None,
        counter: int | None = None,
    ) -> Event:
        from varde_data.friction_events import make_event

        return make_event(ts, repo, body, pid=pid, counter=counter)

    @classmethod
    def new(cls, repo: str | None, body: EventBody) -> Event:
        from varde_data.friction_events import new_event

        return new_event(repo, body)

    def validate(self) -> None:
        from varde_data.friction_events import validate_event

        validate_event(self)

    def to_dict(self) -> dict[str, Any]:
        from varde_data.friction_events import event_to_dict

        return event_to_dict(self)


@dataclass(frozen=True)
class LogReplay:
    events: list[Event]
    torn_line: str | None = None
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class LogItem:
    event_id: str
    slug: str
    title: str
    source: str
    repo_root: str | None
    target: str | None
    status: str
    created_at: str
    tags: list[str]


@dataclass(frozen=True)
class LogOccurrence:
    event_id: str
    item_event_id: str
    at: str
    cwd: str
    repo_root: str | None
    head_sha: str | None
    evidence: str
    cost: str | None
    provenance: dict[str, Any] | None


@dataclass(frozen=True)
class LogStatusChange:
    event_id: str
    item_event_id: str
    at: str
    from_: str
    to: str
    reason: str


@dataclass(frozen=True)
class LogAdoption:
    event_id: str
    at: str
    summary: str
    files: list[str]
    commit_sha: str | None
    eval_before: str | None
    eval_after: str | None
    item_event_ids: list[str]


@dataclass(frozen=True)
class LogState:
    items: list[LogItem]
    occurrences: list[LogOccurrence]
    status_changes: list[LogStatusChange]
    adoptions: list[LogAdoption]
    orphaned_events: int


@dataclass(frozen=True)
class FrictionEventLog:
    events: tuple[Event, ...]
    lines: tuple[str, ...]
    torn_tail: str
    state: LogState
    grouped_occurrences: dict[str, tuple[LogOccurrence, ...]]
