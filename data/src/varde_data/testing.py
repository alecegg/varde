"""Plain helpers shared by data repository contract tests."""

import hashlib
import json
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from varde_data.backends.files.plans_write import (
    PlansWriter,
    Record,
    _apply_update,
    _record_from_bytes,
)
from varde_data.errors import Conflict, Invalid, NotFound
from varde_data.fixture_domain import FilesNotes, MemoryNotes, NotesRepository
from varde_data.friction_events import (
    _validate_event_provenance,
    append_many_checked,
    fold,
    fold_store,
    redact_text,
)
from varde_data.friction_events import append as append_friction_event
from varde_data.friction_events import append_many as append_friction_events
from varde_data.friction_ops import filter_items, list_recurrences, plan_import_entries
from varde_data.records.friction import (
    AdoptionRecorded,
    Event,
    EventBody,
    FrictionEventLog,
    ItemAdded,
    ItemTagsChanged,
    LogItem,
    OccurrenceAppended,
    StatusChanged,
)
from varde_data.records.ledger import Digest, LedgerRow
from varde_data.records.plans import PlanRecord, ReadResult, TaskRecord
from varde_data.repos.friction import (
    AdoptionRequest,
    FrictionAddRequest,
    FrictionEventImportResult,
    FrictionExportItem,
    FrictionImportEntry,
    FrictionImportResult,
    FrictionPage,
    FrictionRecurrenceReport,
    FrictionShow,
    FrictionStatusRequest,
    HistoricalCapture,
    HistoricalCaptureRequest,
    HistoricalWitness,
)
from varde_data.repos.plans import resolve_plan_ref
from varde_data.version import Version, files_version

BackendFactory = Callable[[Path], NotesRepository]


class MemoryLedger:
    """In-memory ledger backend used by repository contract tests."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._rows: list[LedgerRow] = []
        self._digests: dict[str, Digest] = {}
        self._lock = threading.RLock()

    def mark(self, harness, session, when, summary, metrics=None, friction_added=None):
        with self._lock:
            self._rows.append(
                LedgerRow(
                    session, harness, when, summary, metrics or {}, friction_added or []
                )
            )

    def analyzed(self):
        with self._lock:
            latest = {}
            for row in self._rows:
                latest[(row.harness, row.session)] = row
            return list(latest.values())

    def seen(self, harness):
        return {row.session for row in self.analyzed() if row.harness == harness}

    def write_digest(self, run_date, text, candidates):
        with self._lock:
            self._digests[run_date.isoformat()] = Digest(
                run_date.isoformat(), text, candidates
            )

    def read_digest(self, run_date):
        with self._lock:
            return self._digests.get(run_date.isoformat())


def _valid_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def make_working_dir(root: Path) -> Path:
    """Create and return a temporary working directory beneath ``root``."""
    working_dir = root / "working"
    working_dir.mkdir(parents=True, exist_ok=True)
    return working_dir


def backend_registry() -> dict[str, BackendFactory]:
    """Return fixture-domain backend factories keyed by stable backend id."""
    return {"memory": lambda _: MemoryNotes(), "files": FilesNotes}


class MemoryPlans(PlansWriter):
    """In-memory plan reader for the shared contract suite."""

    def __init__(self) -> None:
        self.records: list[PlanRecord] = []

    def list(
        self, *, include_archived: bool = False, include_tasks: bool = True
    ) -> ReadResult:
        records = tuple(r for r in self.records if include_archived or not r.archived)
        if not include_tasks:
            records = tuple(
                replace(record, tasks=(), skipped_tasks=0) for record in records
            )
        return ReadResult(records)

    def get(self, plan_ref: str, *, include_archived: bool = False) -> PlanRecord:
        record = resolve_plan_ref(
            plan_ref, self.list(include_archived=include_archived).records
        )
        if record is None:
            from varde_data.errors import NotFound

            raise NotFound(f"plan {plan_ref!r} not found")
        return record

    def get_by_path(self, path: str) -> PlanRecord:
        for record in self.records:
            if record.path == path:
                return record
            for task in record.tasks:
                if task.path == path:
                    return PlanRecord(
                        task.id,
                        task.fields,
                        task.raw,
                        task.mtime,
                        task.path,
                        artifact_type="task",
                        extra=task.extra,
                    )
        from varde_data.errors import NotFound

        raise NotFound(f"plan file {path!r} not found")

    def owner_lookup(
        self, owner: str, *, include_archived: bool = False
    ) -> tuple[PlanRecord, ...]:
        return tuple(
            r
            for r in self.records
            if (include_archived or not r.archived)
            and r.artifact_type == "plan"
            and r.fields.get("owner") == owner
        )

    def version(self) -> Version:
        return Version(tuple((record.id, record.raw) for record in self.records))

    def _mutate(
        self, expected: Record, update: Callable[[bytes], bytes], *, task: bool
    ) -> Record:
        current = self._current_record(expected)
        updated = _apply_update(update, current.raw)
        parsed = _record_from_bytes(updated, current, task=task, mtime=current.mtime)
        self._store_record(current, parsed, task=task)
        return parsed

    def _current_record(self, expected: Record) -> Record:
        for record in self.records:
            if record.path == expected.path:
                if record.raw != expected.raw:
                    raise Conflict("plan content changed")
                return record
            for task in record.tasks:
                if task.path == expected.path:
                    if task.raw != expected.raw:
                        raise Conflict("plan content changed")
                    return task
        raise NotFound("plan file not found")

    def _store_record(self, current: Record, updated: Record, *, task: bool) -> None:
        for index, plan in enumerate(self.records):
            if plan.path == current.path:
                self.records[index] = replace(
                    plan,
                    fields=updated.fields,
                    raw=updated.raw,
                    extra=updated.extra,
                )
                return
            if task and any(item.path == current.path for item in plan.tasks):
                if not isinstance(updated, TaskRecord):
                    raise Invalid("task writer returned a plan record")
                tasks = tuple(
                    updated if item.path == current.path else item
                    for item in plan.tasks
                )
                self.records[index] = replace(plan, tasks=tasks)
                return


class MemoryFriction:
    """Event-log-backed friction repository fixture used by contract tests."""

    def __init__(
        self, root: Path, *, redactor: Callable[[str], tuple[str, int]] | None = None
    ) -> None:
        self.root = root
        self._lock = threading.RLock()
        self._counter = time.time_ns() // 1_000_000
        self._imported_slugs: dict[str, str] = {}
        self._redactor = redactor or redact_text

    def _events(self) -> list[Event]:
        from varde_data.friction_events import replay

        return replay(self.root / "friction.jsonl").events

    def _state(self):
        state = fold_store(self.root / "friction.jsonl")[0]
        if not self._imported_slugs:
            return state
        return replace(
            state,
            items=[
                replace(item, slug=self._imported_slugs.get(item.event_id, item.slug))
                for item in state.items
            ],
        )

    def version(self) -> Version:
        return files_version([self.root / "friction.jsonl"])

    def event_log(self) -> FrictionEventLog:
        from varde_data.friction_events import event_log

        return event_log(self.root / "friction.jsonl")

    def append_event(self, event: Event) -> Event:
        with self._lock:
            return append_friction_event(self.root, event, redact=self._redactor)

    def append_events(self, events: Iterable[Event]) -> list[Event]:
        with self._lock:
            return append_friction_events(self.root, events, redact=self._redactor)

    def _append_checked(
        self, prepare: Callable[[list[Event]], Iterable[Event]]
    ) -> list[Event]:
        """Replay, choose additions and append them atomically (storage seam)."""
        return append_many_checked(self.root, prepare, redact=self._redactor)

    def _append(self, repo: str | None, body: object) -> Event:
        from varde_data.friction_events import format_timestamp

        self._counter = max(self._counter + 1, time.time_ns() // 1_000_000)
        return self.append_event(
            Event.at(
                format_timestamp(self._counter),
                repo,
                body,  # type: ignore[arg-type]
                pid=0,
                counter=self._counter,
            )
        )

    def _item(self, identifier: str | int) -> tuple[int, LogItem]:
        state = self._state()
        if isinstance(identifier, int) or str(identifier).isdecimal():
            index = int(identifier) - 1
            if 0 <= index < len(state.items):
                return index, state.items[index]
        for index, item in enumerate(state.items):
            if identifier in (item.slug, item.event_id):
                return index, item
        raise NotFound(f"friction item {identifier!r} not found")

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
    ) -> FrictionPage:
        return filter_items(
            self._state(),
            status=status,
            source=source,
            repo_root=repo_root,
            global_=global_,
            tag=tag,
            text=text,
            offset=offset,
            limit=limit,
        )

    def export_items(self):
        state = self._state()
        return tuple(
            FrictionExportItem(
                item,
                tuple(o for o in state.occurrences if o.item_event_id == item.event_id),
                tuple(
                    s for s in state.status_changes if s.item_event_id == item.event_id
                ),
            )
            for item in state.items
        )

    def show(
        self, identifier: str, *, offset: int = 0, limit: int = 100
    ) -> FrictionShow:
        _, item = self._item(identifier)
        state = self._state()
        occurrences = tuple(
            o for o in state.occurrences if o.item_event_id == item.event_id
        )
        changes = tuple(
            s for s in state.status_changes if s.item_event_id == item.event_id
        )
        return FrictionShow(
            item,
            FrictionPage(
                occurrences[offset : offset + limit], len(occurrences), offset, limit
            ),
            FrictionPage(changes[offset : offset + limit], len(changes), offset, limit),
        )

    def add(self, request: FrictionAddRequest) -> LogItem:
        if not request.evidence.strip() or not request.cwd.strip():
            raise Invalid("evidence and cwd are required")
        if any(not re.fullmatch(r"[a-z][a-z0-9-]{0,23}", tag) for tag in request.tags):
            raise Invalid("invalid friction tag")
        if request.item_id is not None:
            with self._lock:
                _, item = self._item(request.item_id)
                tags = sorted(set(request.tags))
                events: list[Event] = []
                if tags:
                    events.append(
                        self._event(None, ItemTagsChanged(item.event_id, tags))
                    )
                events.append(
                    self._event(
                        request.repo_root,
                        OccurrenceAppended(
                            item.event_id,
                            self._timestamp(),
                            request.cwd,
                            request.evidence,
                            request.repo_root,
                            request.head_sha,
                        ),
                    )
                )
                self.append_events(events)
                return self._item(item.event_id)[1]
        if not request.title.strip() or not request.source.strip():
            raise Invalid("title and source are required")
        root = None if request.global_ else request.repo_root
        with self._lock:
            event = self._event(
                root,
                ItemAdded(
                    request.title,
                    request.source,
                    root,
                    request.target,
                    list(request.tags),
                ),
            )
            occurrence = self._event(
                request.repo_root,
                OccurrenceAppended(
                    event.id,
                    event.ts,
                    request.cwd,
                    request.evidence,
                    request.repo_root,
                    request.head_sha,
                ),
            )
            self.append_events([event, occurrence])
            return self._item(event.id)[1]

    def set_status(self, request: FrictionStatusRequest) -> LogItem:
        identifier = request.identifier
        status = request.status
        reason = request.reason
        if not reason.strip():
            raise Invalid("reason must not be blank")
        if status not in {"open", "resolved", "promoted", "archived"}:
            raise Invalid(f"unknown friction status {status!r}")
        with self._lock:
            _, item = self._item(identifier)
            self._append(
                item.repo_root,
                StatusChanged(
                    item.event_id, self._timestamp(), item.status, status, reason
                ),
            )
            return self._item(identifier)[1]

    @staticmethod
    def _timestamp() -> str:
        return (
            datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )

    def _event(self, repo: str | None, body: EventBody) -> Event:
        from varde_data.friction_events import format_timestamp

        self._counter = max(self._counter + 1, time.time_ns() // 1_000_000)
        return Event.at(
            format_timestamp(self._counter), repo, body, pid=0, counter=self._counter
        )

    def record_adoption(self, request: AdoptionRequest):
        if not request.item_ids:
            raise Invalid("at least one item ID is required")
        if any(item_id <= 0 for item_id in request.item_ids):
            raise Invalid("item IDs must be positive")
        if len(set(request.item_ids)) != len(request.item_ids):
            raise Invalid("item IDs must not contain duplicates")
        if (
            not request.summary.strip()
            or not request.files
            or any(not path.strip() for path in request.files)
        ):
            raise Invalid("adoption summary and file paths are required")
        for value in (request.eval_before, request.eval_after):
            if value is not None:
                try:
                    json.loads(value)
                except json.JSONDecodeError as error:
                    raise Invalid("evaluation values must be valid JSON") from error
        with self._lock:
            items = [self._item(identifier)[1] for identifier in request.item_ids]
            events = [
                self._event(
                    item.repo_root,
                    StatusChanged(
                        item.event_id,
                        request.at,
                        item.status,
                        "promoted",
                        "Recorded adoption",
                    ),
                )
                for item in items
            ]
            event = self._event(
                None,
                AdoptionRecorded(
                    request.at,
                    request.summary,
                    list(request.files),
                    [item.event_id for item in items],
                    request.commit_sha,
                    request.eval_before,
                    request.eval_after,
                ),
            )
            events.append(event)
            self.append_events(events)
            return next(a for a in self._state().adoptions if a.event_id == event.id)

    def list_recurrences(
        self, *, offset: int = 0, limit: int = 100
    ) -> FrictionRecurrenceReport:
        return list_recurrences(self._state(), offset=offset, limit=limit)

    def import_entries(
        self, entries: Iterable[FrictionImportEntry], *, dry_run: bool = False
    ) -> FrictionImportResult:
        incoming = list(entries)
        if dry_run:
            return FrictionImportResult(0, 0, True, len(incoming))
        counters = {"imported": 0, "skipped": 0}
        id_map: dict[str, dict[str, int | str]] = {}
        slug_map: dict[str, str] = {}

        def prepare(events: list[Event]) -> list[Event]:
            state = fold(events)
            accepted, skipped = plan_import_entries(
                state, tuple(incoming), imported_slugs=self._imported_slugs
            )
            counters["skipped"] = skipped
            output: list[Event] = []
            for entry in accepted:
                created_at = entry.created_at or self._timestamp()
                item_event = self._event(
                    entry.repo_root,
                    ItemAdded(
                        entry.title,
                        entry.source,
                        entry.repo_root,
                        entry.target,
                        list(entry.tags) or None,
                    ),
                )
                item_event = Event.at(
                    created_at,
                    entry.repo_root,
                    item_event.body,
                    pid=0,
                    counter=self._counter,
                )  # preserve supplied creation time
                output.append(item_event)
                if entry.id is not None and entry.id > 0:
                    id_map.setdefault("items", {})[item_event.id] = entry.id
                output.extend(
                    self._event(
                        None,
                        OccurrenceAppended(
                            item_event.id,
                            occurrence.at,
                            occurrence.cwd,
                            occurrence.evidence,
                            occurrence.repo_root,
                            occurrence.head_sha,
                            occurrence.cost,
                            occurrence.provenance,
                        ),
                    )
                    for occurrence in entry.occurrences
                )
                for occurrence_event, occurrence in zip(
                    output[-len(entry.occurrences) :] if entry.occurrences else (),
                    entry.occurrences,
                    strict=True,
                ):
                    if occurrence.event_id.isdecimal():
                        id_map.setdefault("occurrences", {})[occurrence_event.id] = int(
                            occurrence.event_id
                        )
                change_events = [
                    self._event(
                        None,
                        StatusChanged(
                            item_event.id,
                            change.at,
                            change.from_,
                            change.to,
                            change.reason,
                        ),
                    )
                    for change in entry.status_changes
                ]
                output.extend(change_events)
                for change_event, change in zip(
                    change_events, entry.status_changes, strict=True
                ):
                    if change.event_id.isdecimal():
                        id_map.setdefault("status_changes", {})[change_event.id] = int(
                            change.event_id
                        )
                current_status = (
                    entry.status_changes[-1].to if entry.status_changes else "open"
                )
                if entry.status != current_status:
                    output.append(
                        self._event(
                            None,
                            StatusChanged(
                                item_event.id,
                                created_at,
                                current_status,
                                entry.status,
                                "imported status",
                            ),
                        )
                    )
                counters["imported"] += 1
                slug_map[item_event.id] = entry.slug
            return output

        self._append_checked(prepare)
        self._imported_slugs.update(slug_map)
        id_map.setdefault("item_slugs", {}).update(slug_map)
        return FrictionImportResult(
            counters["imported"], counters["skipped"], False, id_map=id_map
        )

    def import_events(
        self, events: Iterable[Event], *, dry_run: bool = False
    ) -> FrictionEventImportResult:
        incoming = list(events)

        def additions(existing: list[Event]) -> list[Event]:
            by_id = {event.id: event for event in existing}
            result = []
            for event in incoming:
                _validate_event_provenance(event)
                saved = by_id.get(event.id)
                if saved is not None:
                    if saved.to_dict() != event.to_dict():
                        raise Conflict(
                            f"conflicting payload for friction event `{event.id}`"
                        )
                    continue
                result.append(event)
            return result

        if dry_run:
            present = len(incoming) - len(additions(self._events()))
            return FrictionEventImportResult(0, present, True)
        added = self._append_checked(additions)
        return FrictionEventImportResult(len(added), len(incoming) - len(added), False)

    def find_historical_witness(
        self, *, harness: str, thread_id: str, witness_id: str
    ) -> tuple[HistoricalWitness, ...]:
        if not harness.strip() or not thread_id.strip() or not witness_id.strip():
            raise Invalid("historical witness values must not be blank")
        found = []
        for event in self._events():
            body = event.body
            if isinstance(body, OccurrenceAppended) and body.provenance:
                provenance = body.provenance
                if (
                    provenance.get("harness") == harness
                    and provenance.get("thread_id") == thread_id
                    and provenance.get("witness_id") == witness_id
                ):
                    found.append(
                        HistoricalWitness(
                            **{
                                key: provenance[key]
                                for key in HistoricalWitness.__dataclass_fields__
                            }
                        )
                    )
        return tuple(found)

    def find_historical_fallback_witness(
        self, *, harness: str, thread_id: str, record_index: int, record_digest: str
    ) -> tuple[HistoricalWitness, ...]:
        found = []
        for event in self._events():
            body = event.body
            if not isinstance(body, OccurrenceAppended) or not body.provenance:
                continue
            provenance = body.provenance
            if (
                provenance.get("harness") == harness
                and provenance.get("thread_id") == thread_id
                and provenance.get("witness_id") is None
                and (
                    provenance.get("record_index") == record_index
                    or provenance.get("record_digest") == record_digest
                )
            ):
                found.append(
                    HistoricalWitness(
                        **{
                            key: provenance[key]
                            for key in HistoricalWitness.__dataclass_fields__
                        }
                    )
                )
        return tuple(found)

    def record_historical(self, request: HistoricalCaptureRequest) -> HistoricalCapture:
        occurrence = request.occurrence
        if (
            not occurrence.at.strip()
            or not occurrence.cwd.strip()
            or not occurrence.evidence.strip()
        ):
            raise Invalid(
                "historical occurrence time, cwd, and evidence must not be blank"
            )
        witness = occurrence.witness
        identity = {
            "identity_version": 1,
            "harness": witness.harness,
            "thread_id": witness.thread_id,
            "incident_kind": witness.incident_kind,
            "event": {"native_id": witness.witness_id}
            if witness.witness_id is not None
            else {
                "record_index": witness.record_index,
                "record_digest": witness.record_digest,
            },
        }
        key = (
            "incident-v1:"
            + hashlib.sha256(
                json.dumps(
                    identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest()
        )
        result: dict[str, object] = {}

        def prepare(events: list[Event]) -> list[Event]:
            state = fold(events)
            if request.mode.kind == "append":
                if (
                    request.mode.item_id is None
                    or request.mode.item_id <= 0
                    or request.mode.item_id > len(state.items)
                ):
                    raise NotFound(f"friction item {request.mode.item_id!r} not found")
                item = state.items[request.mode.item_id - 1]
            elif request.mode.kind == "create":
                if (
                    not request.mode.source
                    or not request.mode.source.strip()
                    or not request.mode.title
                    or not request.mode.title.strip()
                ):
                    raise Invalid("historical source and title are required")
                item = None
            else:
                raise Invalid("unknown historical item mode")
            for saved in state.occurrences:
                facts = saved.provenance or {}
                if facts.get("incident_key") != key:
                    continue
                if (
                    saved.at,
                    saved.cwd,
                    saved.evidence,
                    saved.repo_root,
                    saved.head_sha,
                ) != (
                    occurrence.at,
                    occurrence.cwd,
                    occurrence.evidence,
                    occurrence.repo_root,
                    occurrence.head_sha,
                ):
                    raise Conflict(f"historical incident {key!r} conflicts")
                result.update(
                    item=self._item(saved.item_event_id)[1],
                    occurrence=saved,
                    created=False,
                )
                return []
            output: list[Event] = []
            if item is None:
                item_event = self._event(
                    request.mode.repo_root,
                    ItemAdded(
                        request.mode.title or "",
                        request.mode.source or "",
                        request.mode.repo_root,
                        request.mode.target,
                    ),
                )
                output.append(item_event)
                item_id = item_event.id
            else:
                item_id = item.event_id
            provenance = dict(occurrence.canonical_facts)
            provenance.update(
                {
                    name: getattr(witness, name)
                    for name in HistoricalWitness.__dataclass_fields__
                }
            )
            provenance.update(incident_key=key, identity_version=1)
            provenance.setdefault(
                "payload_digest",
                hashlib.sha256(
                    json.dumps(
                        occurrence.canonical_facts,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode()
                ).hexdigest(),
            )
            event = self._event(
                None,
                OccurrenceAppended(
                    item_id,
                    occurrence.at,
                    occurrence.cwd,
                    occurrence.evidence,
                    occurrence.repo_root,
                    occurrence.head_sha,
                    None,
                    provenance,
                ),
            )
            output.append(event)
            result.update(item_id=item_id, event_id=event.id, created=True)
            return output

        with self._lock:
            self._append_checked(prepare)
        state = self._state()
        if "occurrence" in result:
            return HistoricalCapture(result["item"], result["occurrence"], False)  # type: ignore[arg-type]
        saved = next(
            value for value in state.occurrences if value.event_id == result["event_id"]
        )
        return HistoricalCapture(self._item(saved.item_event_id)[1], saved, True)
