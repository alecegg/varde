"""Pure friction queries over folded event-log state."""

from __future__ import annotations

from datetime import UTC, datetime

from varde_data.errors import Conflict, Invalid
from varde_data.records.friction import LogItem, LogState
from varde_data.repos.friction import (
    FrictionImportEntry,
    FrictionPage,
    FrictionRecurrence,
    FrictionRecurrenceReport,
)


def filter_items(  # noqa: PLR0913 - mirrors the friction list filters
    state: LogState,
    *,
    status: str | None = None,
    source: str | None = None,
    repo_root: str | None = None,
    global_: bool = False,
    tag: str | None = None,
    text: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> FrictionPage[LogItem]:
    if global_ and repo_root is not None:
        raise Invalid("--repo and --global cannot be combined")
    if offset < 0 or limit < 1 or limit > 1_000:
        raise Invalid("invalid friction page")
    if source is not None and not source.strip():
        raise Invalid("source must not be blank")
    if text is not None and not text.strip():
        raise Invalid("text must not be blank")
    if tag is not None and not __import__("re").fullmatch(r"[a-z][a-z0-9-]{0,23}", tag):
        raise Invalid("invalid friction tag")
    items = state.items
    if status is not None:
        items = [item for item in items if item.status == status]
    if source is not None:
        items = [item for item in items if item.source == source]
    if global_:
        items = [item for item in items if item.repo_root is None]
    elif repo_root is not None:
        items = [item for item in items if item.repo_root == repo_root]
    if tag is not None:
        items = [item for item in items if tag in item.tags]
    if text is not None:
        needle = text.lower()
        items = [
            item
            for item in items
            if needle in item.title.lower()
            or any(
                occurrence.item_event_id == item.event_id
                and needle in occurrence.evidence.lower()
                for occurrence in state.occurrences
            )
        ]
    return FrictionPage(
        tuple(items[offset : offset + limit]), len(items), offset, limit
    )


def list_recurrences(
    state: LogState, *, offset: int = 0, limit: int = 100
) -> FrictionRecurrenceReport:
    if offset < 0 or limit < 1 or limit > 1_000:
        raise Invalid("invalid friction page")
    by_id = {item.event_id: item for item in state.items}
    valid_adoptions = []
    for adoption in state.adoptions:
        adopted_at = _parse_timestamp(adoption.at)
        if adopted_at is not None:
            valid_adoptions.append((adoption, adopted_at))
    invalid = sum(
        not _valid_timestamp(a.at)
        for a in state.adoptions
        if any(i in by_id for i in a.item_event_ids)
    )
    invalid += sum(
        not _valid_timestamp(o.at)
        for o in state.occurrences
        if any(o.item_event_id in a.item_event_ids for a in state.adoptions)
    )
    rows: list[FrictionRecurrence] = []
    for occurrence in state.occurrences:
        item = by_id.get(occurrence.item_event_id)
        if item is None or not _valid_timestamp(occurrence.at):
            continue
        occurrence_time = _parse_timestamp(occurrence.at)
        if occurrence_time is None:
            continue
        applicable = [
            (adoption, adopted_at)
            for adoption, adopted_at in valid_adoptions
            if item.event_id in adoption.item_event_ids and occurrence_time > adopted_at
        ]
        if applicable:
            adoption, _ = max(applicable, key=lambda row: (row[1], row[0].event_id))
            rows.append(FrictionRecurrence(adoption, item, occurrence))
    rows.sort(
        key=lambda row: (
            _parse_timestamp(row.occurrence.at),
            row.occurrence.event_id,
        )
    )
    return FrictionRecurrenceReport(
        FrictionPage(tuple(rows[offset : offset + limit]), len(rows), offset, limit),
        invalid,
    )


def plan_import_entries(
    state: LogState,
    entries: tuple[FrictionImportEntry, ...],
    *,
    imported_slugs: dict[str, str] | None = None,
) -> tuple[tuple[FrictionImportEntry, ...], int]:
    """Select new entries and validate historical dedupe against folded state."""
    slug_map = imported_slugs or {}
    slugs = {slug_map.get(item.event_id, item.slug) for item in state.items}
    keys = {
        occurrence.provenance.get("incident_key")
        for occurrence in state.occurrences
        if occurrence.provenance
    }
    accepted: list[FrictionImportEntry] = []
    skipped = 0
    for entry in entries:
        if entry.slug in slugs:
            skipped += 1
            continue
        incoming_keys = [
            occurrence.provenance.get("incident_key")
            for occurrence in entry.occurrences
            if occurrence.provenance
        ]
        if any(key in keys for key in incoming_keys) or len(set(incoming_keys)) != len(
            incoming_keys
        ):
            raise Conflict("historical provenance already exists")
        accepted.append(entry)
        slugs.add(entry.slug)
        keys.update(key for key in incoming_keys if key is not None)
    return tuple(accepted), skipped


def _valid_timestamp(value: str) -> bool:
    return _parse_timestamp(value) is not None


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
