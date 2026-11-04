"""Convert shared friction records to learn's output DTOs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from varde_data.errors import NotFound
from varde_data.friction import open_friction
from varde_data.records.friction import (
    AdoptionRecorded,
    ItemAdded,
    LogAdoption,
    LogItem,
    LogOccurrence,
    LogStatusChange,
    OccurrenceAppended,
    StatusChanged,
)
from varde_data.repos.friction import FrictionRepository

from .errors import StoreItemNotFound
from .store.paths import resolve_store_dir, validate_store_path
from .store.types import (
    AdoptionRecord,
    FrictionIncidentProvenance,
    FrictionItem,
    FrictionOccurrence,
    FrictionStatusChange,
)


@dataclass
class EventNumbers:
    """Numeric learn IDs indexed once from a repository event log."""

    items: dict[str, int] = field(default_factory=dict)
    occurrences: dict[str, int] = field(default_factory=dict)
    status_changes: dict[str, int] = field(default_factory=dict)
    adoptions: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_repository(cls, repository: FrictionRepository) -> EventNumbers:
        numbers = cls()
        counters = (
            (ItemAdded, numbers.items),
            (OccurrenceAppended, numbers.occurrences),
            (StatusChanged, numbers.status_changes),
            (AdoptionRecorded, numbers.adoptions),
        )
        for event in repository.event_log().events:
            for body_type, mapping in counters:
                if isinstance(event.body, body_type):
                    mapping[event.id] = len(mapping) + 1
                    break
        return numbers


def open_repository(root: Path | None = None) -> FrictionRepository:
    store_root = root or resolve_store_dir()
    validate_store_path(store_root)
    return open_friction(store_root)


def with_repository[T](
    operation: Callable[[FrictionRepository], T], root: Path | None = None
) -> T:
    """Run an operation with the validated friction repository."""
    return operation(open_repository(root))


def show(
    repository: FrictionRepository,
    identifier: str,
    *,
    offset: int = 0,
    limit: int = 100,
):
    try:
        return repository.show(identifier, offset=offset, limit=limit)
    except NotFound as error:
        raise StoreItemNotFound(identifier) from error


def item(
    repository: FrictionRepository,
    record: LogItem,
    numbers: EventNumbers | None = None,
) -> FrictionItem:
    identifier = item_identifier(
        repository, record, numbers or EventNumbers.from_repository(repository)
    )
    return FrictionItem(
        identifier,
        record.slug,
        record.title,
        record.source,
        record.repo_root,
        record.status,
        record.target,
        record.created_at,
        list(record.tags),
    )


def item_identifier(
    repository: FrictionRepository,
    record: LogItem,
    numbers: EventNumbers | None = None,
) -> int:
    lookup = numbers or EventNumbers.from_repository(repository)
    return lookup.items[record.event_id]


def occurrence(
    repository: FrictionRepository,
    record: LogOccurrence,
    numbers: EventNumbers | None = None,
) -> FrictionOccurrence:
    lookup = numbers or EventNumbers.from_repository(repository)
    identifier = lookup.occurrences[record.event_id]
    item_id = lookup.items[record.item_event_id]
    provenance_fields = FrictionIncidentProvenance.__dataclass_fields__
    provenance = (
        FrictionIncidentProvenance(
            **{
                key: value
                for key, value in record.provenance.items()
                if key in provenance_fields
            }
        )
        if record.provenance
        and all(key in record.provenance for key in provenance_fields)
        else None
    )
    return FrictionOccurrence(
        identifier,
        item_id,
        record.at,
        record.cwd,
        record.repo_root,
        record.head_sha,
        record.evidence,
        record.cost,
        provenance,
    )


def status_change(
    repository: FrictionRepository,
    record: LogStatusChange,
    numbers: EventNumbers | None = None,
) -> FrictionStatusChange:
    lookup = numbers or EventNumbers.from_repository(repository)
    identifier = lookup.status_changes[record.event_id]
    item_id = lookup.items[record.item_event_id]
    return FrictionStatusChange(
        identifier, item_id, record.at, record.from_, record.to, record.reason
    )


def adoption(
    repository: FrictionRepository,
    record: LogAdoption,
    numbers: EventNumbers | None = None,
) -> AdoptionRecord:
    lookup = numbers or EventNumbers.from_repository(repository)
    identifier = lookup.adoptions[record.event_id]
    item_ids = [lookup.items[event_id] for event_id in record.item_event_ids]
    return AdoptionRecord(
        identifier,
        record.at,
        record.summary,
        list(record.files),
        record.commit_sha,
        record.eval_before,
        record.eval_after,
        item_ids,
    )


def adoption_id(
    repository: FrictionRepository,
    record: LogAdoption,
    numbers: EventNumbers | None = None,
) -> int:
    lookup = numbers or EventNumbers.from_repository(repository)
    return lookup.adoptions[record.event_id]
