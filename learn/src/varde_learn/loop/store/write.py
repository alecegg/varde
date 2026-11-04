"""Write friction through FrictionRepository."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from varde_data.friction_events import now_timestamp
from varde_data.records.friction import (
    AdoptionRecorded,
    Event,
    ItemAdded,
    ItemTagsChanged,
    OccurrenceAppended,
    StatusChanged,
)

from .. import friction_repository
from ..errors import StoreItemNotFound
from .types import (
    AdoptionRecordRequest,
    FrictionAddRequest,
    FrictionItem,
    HistoricalCaptureRequest,
    HistoricalCaptureResult,
    incident_conflict,
    invalid_store_input,
    provenance_for,
    repository_context,
    require_nonblank,
    validate_provenance,
    validate_tag,
)


def _item(repository, item_id: int) -> FrictionItem:
    try:
        record = friction_repository.show(repository, str(item_id)).item
    except Exception as error:
        if getattr(error, "code", None) in {"not_found", "item_not_found"}:
            raise StoreItemNotFound(str(item_id)) from error
        raise
    return friction_repository.item(repository, record)


def _item_event_id(repository, item_id: int) -> str:
    return repository.show(str(item_id)).item.event_id


def set_friction_status(repository, item_id, status, reason):
    if item_id <= 0:
        raise invalid_store_input("item ID must be a positive integer")
    require_nonblank(reason, "reason")
    item = _item(repository, item_id)
    event = Event.at(
        _next_timestamp(repository, now_timestamp()),
        item.repo_root,
        StatusChanged(
            _item_event_id(repository, item_id),
            now_timestamp(),
            item.status,
            _status(status),
            reason,
        ),
    )
    repository.import_events((event,))
    return _item(repository, item_id)


def record_adoption(repository, request: AdoptionRecordRequest):
    timestamp = now_timestamp()
    state = repository.event_log().state
    adoption_id = len(state.adoptions) + 1
    items = [_item(repository, item_id) for item_id in request.item_ids]
    events = []
    event_at = _next_timestamp(repository, now_timestamp())
    for item in items:
        events.append(
            Event.at(
                event_at,
                item.repo_root,
                StatusChanged(
                    _item_event_id(repository, item.id),
                    timestamp,
                    item.status,
                    "promoted",
                    f"Recorded adoption {adoption_id}",
                ),
            )
        )
        event_at = _bump(event_at)
    events.append(
        Event.at(
            event_at,
            None,
            AdoptionRecorded(
                timestamp,
                request.summary,
                list(request.files),
                [_item_event_id(repository, item.id) for item in items],
                request.commit_sha,
                request.eval_before,
                request.eval_after,
            ),
        )
    )
    repository.import_events(events)
    return friction_repository.adoption(
        repository, repository.event_log().state.adoptions[-1]
    )


def add_friction(repository, request: FrictionAddRequest) -> FrictionItem:
    require_nonblank(request.evidence, "evidence")
    if not str(request.cwd):
        raise invalid_store_input("cwd must not be blank")
    mode = request.mode
    context = repository_context(request.cwd)
    tags = tuple(sorted({validate_tag(tag) for tag in request.tags}))
    if mode.kind == "create":
        require_nonblank(mode.title or "", "title")
        require_nonblank(mode.source or "", "source")
        item_root = None if mode.global_ else context.repo_root
        created_at = _next_timestamp(repository, now_timestamp())
        added = Event.at(
            created_at,
            item_root,
            ItemAdded(
                mode.title or "", mode.source or "", item_root, mode.target, list(tags)
            ),
        )
        item_event_id = added.id
        occurrence_at = created_at
        occurrence_ts = _bump(created_at)
        events = [added]
    elif mode.kind == "append":
        if mode.item_id is None or mode.item_id <= 0:
            raise invalid_store_input("item ID must be a positive integer")
        item = _item(repository, mode.item_id)
        item_event_id = _item_event_id(repository, item.id)
        occurrence_ts = _next_timestamp(repository, now_timestamp())
        occurrence_at = now_timestamp()
        events = []
        if tags:
            events.append(
                Event.at(
                    _bump(occurrence_ts),
                    None,
                    ItemTagsChanged(item_event_id, list(tags)),
                )
            )
    else:
        raise invalid_store_input("unknown friction add mode")
    events.append(
        Event.at(
            occurrence_ts,
            context.repo_root,
            OccurrenceAppended(
                item_event_id,
                occurrence_at,
                str(request.cwd),
                request.evidence,
                context.repo_root,
                context.head_sha,
            ),
        )
    )
    repository.import_events(events)
    record = next(
        value
        for value in repository.event_log().state.items
        if value.event_id == item_event_id
    )
    return friction_repository.item(repository, record)


def import_friction(repository, entry: Any):
    if any(item.slug == entry.slug for item in repository.event_log().state.items):
        return None
    for occurrence in entry.occurrences:
        if occurrence.provenance is not None:
            validate_provenance(occurrence.provenance)
    created_at = entry.created_at or now_timestamp()
    item_event = Event.at(
        created_at,
        entry.repo_root,
        ItemAdded(
            entry.title,
            entry.source,
            entry.repo_root,
            entry.target,
            list(entry.tags) or None,
        ),
    )
    events = [item_event]
    event_at = _bump(created_at)
    for value in entry.occurrences:
        events.append(
            Event.at(
                event_at,
                None,
                OccurrenceAppended(
                    item_event.id,
                    value.at,
                    value.cwd,
                    value.evidence,
                    value.repo_root,
                    value.head_sha,
                    value.cost,
                    asdict(value.provenance) if value.provenance is not None else None,
                ),
            )
        )
        event_at = _bump(event_at)
    for value in entry.status_changes:
        events.append(
            Event.at(
                event_at,
                None,
                StatusChanged(
                    item_event.id,
                    value.at,
                    value.from_status,
                    value.to_status,
                    value.reason,
                ),
            )
        )
        event_at = _bump(event_at)
    current_status = (
        entry.status_changes[-1].to_status if entry.status_changes else "open"
    )
    wanted_status = _status(entry.status)
    if current_status != wanted_status:
        events.append(
            Event.at(
                event_at,
                None,
                StatusChanged(
                    item_event.id,
                    entry.created_at or now_timestamp(),
                    current_status,
                    wanted_status,
                    "imported status",
                ),
            )
        )
    repository.import_events(events)
    record = next(
        item
        for item in repository.event_log().state.items
        if item.event_id == item_event.id
    )
    return friction_repository.item(repository, record)


def record_historical_occurrence(
    repository, request: HistoricalCaptureRequest
) -> HistoricalCaptureResult:
    mode, occurrence = request.mode, request.occurrence
    provenance = provenance_for(occurrence)
    if mode.kind == "append":
        if mode.item_id is None or mode.item_id <= 0:
            raise invalid_store_input("item ID must be a positive integer")
        item = _item(repository, mode.item_id)
    elif mode.kind == "create":
        require_nonblank(mode.source or "", "source")
        require_nonblank(mode.title or "", "title")
        item = None
    else:
        raise invalid_store_input("unknown historical item mode")

    state = repository.event_log().state
    witness = occurrence.witness
    matches = []
    if witness.witness_id is None:
        matches.extend(
            repository.find_historical_fallback_witness(
                harness=witness.harness,
                thread_id=witness.thread_id,
                record_index=witness.record_index,
                record_digest=witness.record_digest,
            )
        )
    matches.extend(
        repository.find_historical_witness(
            harness=witness.harness,
            thread_id=witness.thread_id,
            witness_id=witness.witness_id or "",
        )
        if witness.witness_id is not None
        else ()
    )
    matches = [
        value for value in matches if value.incident_kind == witness.incident_kind
    ]
    keyed = [
        value
        for value in state.occurrences
        if value.provenance
        and value.provenance.get("incident_key") == provenance.incident_key
    ]
    if matches or keyed:
        if len(keyed) != 1:
            raise incident_conflict(provenance.incident_key)
        saved = keyed[0]
        facts = saved.provenance or {}
        if (
            facts.get("payload_digest") != provenance.payload_digest
            or saved.at != occurrence.at
            or saved.cwd != occurrence.cwd
            or saved.repo_root != occurrence.repo_root
            or saved.head_sha != occurrence.head_sha
        ):
            raise incident_conflict(provenance.incident_key)
        saved_item = next(
            value for value in state.items if value.event_id == saved.item_event_id
        )
        return HistoricalCaptureResult(
            friction_repository.item(repository, saved_item),
            friction_repository.occurrence(repository, saved),
            False,
        )

    if item is None:
        created_at = _next_timestamp(repository, now_timestamp())
        added = Event.at(
            created_at,
            mode.repo_root,
            ItemAdded(mode.title or "", mode.source or "", mode.repo_root, mode.target),
        )
        item_event_id = added.id
        events = [added]
        occurrence_at = _bump(created_at)
    else:
        item_event_id = _item_event_id(repository, item.id)
        occurrence_at = _next_timestamp(repository, now_timestamp())
        events = []
    events.append(
        Event.at(
            occurrence_at,
            None,
            OccurrenceAppended(
                item_event_id,
                occurrence.at,
                occurrence.cwd,
                occurrence.evidence,
                occurrence.repo_root,
                occurrence.head_sha,
                None,
                asdict(provenance),
            ),
        )
    )
    repository.import_events(events)
    updated = repository.event_log().state
    saved = next(
        value
        for value in updated.occurrences
        if value.provenance
        and value.provenance.get("incident_key") == provenance.incident_key
    )
    saved_item = next(
        value for value in updated.items if value.event_id == item_event_id
    )
    # File backends refresh their derived cache on reads after append-only imports.
    repository.show(
        str(
            next(
                i
                for i, value in enumerate(updated.items, 1)
                if value.event_id == item_event_id
            )
        )
    )
    return HistoricalCaptureResult(
        friction_repository.item(repository, saved_item),
        friction_repository.occurrence(repository, saved),
        True,
    )


def _status(value: Any) -> str:
    return value.as_str() if hasattr(value, "as_str") else str(value)


def _next_timestamp(repository, now: str) -> str:
    events = repository.event_log().events
    previous = max((event.ts for event in events), default="")
    return now if now > previous else _bump(previous)


def _bump(timestamp: str) -> str:
    value = datetime.fromisoformat(timestamp)
    return (value + timedelta(milliseconds=1)).astimezone(UTC).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:23] + "Z"
