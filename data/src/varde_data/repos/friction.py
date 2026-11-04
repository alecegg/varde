"""Backend-neutral API for the append-only friction store."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from varde_data.records.friction import (
    Event,
    FrictionEventLog,
    LogAdoption,
    LogItem,
    LogOccurrence,
    LogStatusChange,
)
from varde_data.version import Version


@dataclass(frozen=True)
class FrictionPage[T]:
    items: tuple[T, ...]
    total: int
    offset: int = 0
    limit: int = 100

    @property
    def next_offset(self) -> int | None:
        next_offset = self.offset + len(self.items)
        return None if next_offset >= self.total else next_offset

    @property
    def truncated(self) -> bool:
        return self.next_offset is not None


@dataclass(frozen=True)
class FrictionShow:
    item: LogItem
    occurrences: FrictionPage[LogOccurrence]
    status_changes: FrictionPage[LogStatusChange]


@dataclass(frozen=True)
class FrictionExportItem:
    item: LogItem
    occurrences: tuple[LogOccurrence, ...]
    status_changes: tuple[LogStatusChange, ...]


@dataclass(frozen=True)
class FrictionImportResult:
    imported: int
    skipped: int
    dry_run: bool
    would_import: int = 0
    id_map: dict[str, dict[str, int | str]] | None = None


@dataclass(frozen=True)
class FrictionImportEntry:
    slug: str
    title: str
    source: str
    status: str = "open"
    repo_root: str | None = None
    target: str | None = None
    created_at: str | None = None
    tags: tuple[str, ...] = ()
    occurrences: tuple[LogOccurrence, ...] = ()
    status_changes: tuple[LogStatusChange, ...] = ()
    id: int | None = None


@dataclass(frozen=True)
class HistoricalCapture:
    item: LogItem
    occurrence: LogOccurrence
    created: bool


@dataclass(frozen=True)
class HistoricalWitness:
    harness: str
    thread_id: str
    incident_kind: str
    witness_id: str | None
    source_id: str
    record_index: int
    byte_start: int
    byte_end: int
    record_digest: str


@dataclass(frozen=True)
class HistoricalOccurrenceRequest:
    at: str
    cwd: str
    repo_root: str | None
    head_sha: str | None
    evidence: str
    canonical_facts: dict[str, object]
    witness: HistoricalWitness


@dataclass(frozen=True)
class HistoricalItemMode:
    kind: str
    item_id: int | None = None
    source: str | None = None
    title: str | None = None
    target: str | None = None
    repo_root: str | None = None

    @classmethod
    def append(cls, item_id: int) -> HistoricalItemMode:
        return cls("append", item_id=item_id)

    @classmethod
    def create(
        cls, source: str, title: str, target: str | None, repo_root: str | None
    ) -> HistoricalItemMode:
        return cls(
            "create", source=source, title=title, target=target, repo_root=repo_root
        )


@dataclass(frozen=True)
class HistoricalCaptureRequest:
    mode: HistoricalItemMode
    occurrence: HistoricalOccurrenceRequest


@dataclass(frozen=True)
class FrictionEventImportResult:
    imported: int
    present: int
    dry_run: bool


@dataclass(frozen=True)
class FrictionRecurrence:
    adoption: LogAdoption
    item: LogItem
    occurrence: LogOccurrence


@dataclass(frozen=True)
class FrictionRecurrenceReport:
    page: FrictionPage[FrictionRecurrence]
    skipped_invalid_timestamps: int


@dataclass(frozen=True)
class FrictionAddRequest:
    title: str
    source: str
    evidence: str
    cwd: str
    repo_root: str | None = None
    target: str | None = None
    tags: tuple[str, ...] = ()
    head_sha: str | None = None
    global_: bool = False
    item_id: int | None = None


@dataclass(frozen=True)
class AdoptionRequest:
    item_ids: tuple[int, ...]
    summary: str
    files: tuple[str, ...]
    at: str
    commit_sha: str | None = None
    eval_before: str | None = None
    eval_after: str | None = None


@dataclass(frozen=True)
class FrictionStatusRequest:
    identifier: str
    status: str
    reason: str


class FrictionRepository(Protocol):
    """Read and mutate friction data without exposing backend details."""

    def event_log(self) -> FrictionEventLog: ...

    def list_items(  # noqa: PLR0913 - mirrors the friction list filters
        self,
        *,
        status: str | None = None,
        source: str | None = None,
        repo_root: str | None = None,
        global_: bool = False,
        tag: str | None = None,
        text: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> FrictionPage[LogItem]: ...
    def show(
        self, identifier: str, *, offset: int = 0, limit: int = 100
    ) -> FrictionShow: ...
    def export_items(self) -> tuple[FrictionExportItem, ...]: ...
    def list_recurrences(
        self, *, offset: int = 0, limit: int = 100
    ) -> FrictionRecurrenceReport: ...
    def add(self, request: FrictionAddRequest) -> LogItem: ...
    def set_status(self, request: FrictionStatusRequest) -> LogItem: ...
    def record_adoption(self, request: AdoptionRequest) -> LogAdoption: ...
    def import_entries(
        self, entries: Iterable[FrictionImportEntry], *, dry_run: bool = False
    ) -> FrictionImportResult: ...
    def import_events(
        self, events: Iterable[Event], *, dry_run: bool = False
    ) -> FrictionEventImportResult: ...
    def find_historical_witness(
        self, *, harness: str, thread_id: str, witness_id: str
    ) -> tuple[HistoricalWitness, ...]: ...
    def find_historical_fallback_witness(
        self, *, harness: str, thread_id: str, record_index: int, record_digest: str
    ) -> tuple[HistoricalWitness, ...]: ...
    def record_historical(
        self, request: HistoricalCaptureRequest
    ) -> HistoricalCapture: ...
    def version(self) -> Version: ...
