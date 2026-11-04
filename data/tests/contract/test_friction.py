from __future__ import annotations

import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from friction_backends import Backend, backend_registry
from varde_data.errors import Conflict, Invalid, NotFound
from varde_data.friction_events import replay
from varde_data.records.friction import Event, ItemAdded, LogOccurrence
from varde_data.repos.friction import (
    AdoptionRequest,
    FrictionAddRequest,
    FrictionImportEntry,
    FrictionRepository,
    FrictionStatusRequest,
    HistoricalCaptureRequest,
    HistoricalItemMode,
    HistoricalOccurrenceRequest,
    HistoricalWitness,
)


@pytest.fixture(params=tuple(backend_registry()), ids=tuple(backend_registry()))
def backend(request: pytest.FixtureRequest) -> Backend:
    return backend_registry()[request.param]


@pytest.fixture
def store(backend: Backend, tmp_path: Path) -> FrictionRepository:
    return backend.factory(tmp_path)


def add(store: FrictionRepository, title: str = "Alpha friction"):
    return store.add(
        FrictionAddRequest(title, "session", "again", "/work", "/repo", tags=("one",))
    )


def _process_append(root: str, backend_name: str, slug: str) -> None:
    backend = backend_registry()[backend_name]
    backend.factory(Path(root)).import_entries(
        [FrictionImportEntry(slug, slug.replace("-", " "), "process")]
    )


def test_add_list_show_export_and_status(store: FrictionRepository) -> None:
    item = add(store)
    assert item.slug == "alpha-friction"
    assert item.tags == ["one"]
    assert store.list_items().items == (item,)
    assert store.show(item.slug).item == item
    assert store.show(item.slug).occurrences.total == 1
    assert store.export_items()[0].occurrences[0].evidence == "again"
    updated = store.set_status(
        FrictionStatusRequest(item.event_id, "resolved", "fixed")
    )
    assert updated.status == "resolved"
    assert store.show(item.slug).status_changes.total == 1


def test_show_history_pages_and_export_keeps_all_occurrences(
    store: FrictionRepository,
) -> None:
    item = add(store)
    for evidence in ("second", "third"):
        store.add(FrictionAddRequest("", "", evidence, "/work", "/repo", item_id=1))

    page = store.show(item.slug, offset=1, limit=1)

    assert page.occurrences.total == 3
    assert [occurrence.evidence for occurrence in page.occurrences.items] == ["second"]
    assert [
        occurrence.evidence for occurrence in store.export_items()[0].occurrences
    ] == ["again", "second", "third"]


def test_show_missing_item_raises_not_found(store: FrictionRepository) -> None:
    with pytest.raises(NotFound):
        store.show("missing")


def test_all_mutations_redact_strings_and_persist_notice_counts(
    store: FrictionRepository, backend: Backend, tmp_path: Path
) -> None:
    secret = "AKIA1234567890ABCDEF"  # noqa: S105 - known redaction fixture
    item = store.add(
        FrictionAddRequest(f"Title {secret}", "session", f"Evidence {secret}", "/work")
    )
    store.set_status(
        FrictionStatusRequest(item.event_id, "resolved", f"fixed {secret}")
    )
    store.record_adoption(
        AdoptionRequest(
            (1,), f"adopted {secret}", ("src.py",), "2026-01-01T00:00:00.000Z"
        )
    )
    store.import_entries(
        [FrictionImportEntry("imported", f"Imported {secret}", "session")]
    )
    imported_event = Event.at(
        "2026-01-02T00:00:00.000Z",
        None,
        ItemAdded(f"Imported event {secret}", "session"),
        pid=9,
        counter=1,
    )
    store.import_events([imported_event])
    store.record_historical(
        HistoricalCaptureRequest(
            HistoricalItemMode.create("session", "Historical", None, None),
            HistoricalOccurrenceRequest(
                "2026-01-03T00:00:00.000Z",
                "/work",
                None,
                None,
                f"Historical evidence {secret}",
                {"description": secret},
                HistoricalWitness(
                    "codex",
                    "redaction",
                    "incident",
                    "witness",
                    "source",
                    0,
                    0,
                    1,
                    "a" * 64,
                ),
            ),
        )
    )

    events = backend.events(tmp_path)
    assert secret not in repr([event.to_dict() for event in events])
    assert sum(event.redacted for event in events) == 8


def test_memory_redactor_can_be_injected(tmp_path: Path) -> None:
    from varde_data.testing import MemoryFriction

    def redact(text: str) -> tuple[str, int]:
        return text.replace("private", "[hidden]"), text.count("private")

    store = MemoryFriction(tmp_path, redactor=redact)
    item = store.add(
        FrictionAddRequest("private title", "test", "private evidence", "/work")
    )

    assert item.title == "[hidden] title"
    assert [event.redacted for event in replay(tmp_path / "friction.jsonl").events] == [
        1,
        1,
    ]


def test_append_existing_item_and_filtering(store: FrictionRepository) -> None:
    item = add(store)
    appended = store.add(
        FrictionAddRequest(
            "", "", "more evidence", "/work", "/repo", tags=("two",), item_id=1
        )
    )
    assert appended.event_id == item.event_id
    assert store.show(item.slug).occurrences.total == 2
    assert store.list_items(tag="two").items[0].tags == ["one", "two"]
    assert store.list_items(text="more evidence").total == 1


def test_filters_and_invalid_inputs(store: FrictionRepository) -> None:
    item = add(store)
    store.add(
        FrictionAddRequest(
            "Global", "other", "global evidence", "/work", None, global_=True
        )
    )
    assert store.list_items(source="session", repo_root="/repo").items == (item,)
    assert store.list_items(global_=True).items[0].title == "Global"
    assert store.list_items(offset=1, limit=1).total == 2
    invalid_filters = (
        lambda: store.list_items(limit=0),
        lambda: store.list_items(offset=-1),
        lambda: store.list_items(source=" "),
        lambda: store.list_items(text=" "),
        lambda: store.list_items(tag="Bad Tag"),
        lambda: store.list_items(global_=True, repo_root="/repo"),
    )
    for call in invalid_filters:
        with pytest.raises(Invalid):
            call()
    with pytest.raises(Invalid):
        store.add(FrictionAddRequest("Bad", "session", " ", "/work"))
    with pytest.raises(Invalid):
        store.set_status(FrictionStatusRequest(item.event_id, "unknown", "reason"))


def test_adoption_and_recurrence(store: FrictionRepository) -> None:
    add(store)
    adoption = store.record_adoption(
        AdoptionRequest((1,), "shipped", ("a.py",), "2030-01-02T00:00:00.000Z")
    )
    assert adoption.summary == "shipped"
    occurrence = HistoricalCaptureRequest(
        HistoricalItemMode.append(1),
        HistoricalOccurrenceRequest(
            "2030-01-03T00:00:00.000Z",
            "/work",
            "/repo",
            None,
            "again later",
            {"event": {"summary": "later"}},
            HistoricalWitness(
                "codex",
                "thread-1",
                "friction",
                "witness-1",
                "source",
                0,
                0,
                1,
                "a" * 64,
            ),
        ),
    )
    store.record_historical(occurrence)
    assert store.list_recurrences().page.total == 1


def test_adoption_preserves_benchmarks_and_rolls_back_missing_items(
    store: FrictionRepository, backend: Backend, tmp_path: Path
) -> None:
    add(store)
    before_bytes = backend.read_log(tmp_path)
    request = AdoptionRequest(
        (1, 999),
        "must roll back",
        ("a.py",),
        "2030-01-02T00:00:00.000Z",
        "commit-sha",
        '{"score":0.5}',
        '{"score":0.9}',
    )

    with pytest.raises(NotFound):
        store.record_adoption(request)

    assert backend.read_log(tmp_path) == before_bytes
    record = store.record_adoption(
        AdoptionRequest(
            (1,),
            "adopted",
            ("a.py",),
            "2030-01-02T00:00:00.000Z",
            "commit-sha",
            '{"score":0.5}',
            '{"score":0.9}',
        )
    )
    assert record.eval_before == '{"score":0.5}'
    assert record.eval_after == '{"score":0.9}'
    assert record.files == ["a.py"]


def test_concurrent_adoptions_are_all_recorded(
    backend: Backend, tmp_path: Path
) -> None:
    store = backend.factory(tmp_path)
    item = add(store)
    barrier = Barrier(4)

    def adopt(index: int) -> None:
        barrier.wait()
        store.record_adoption(
            AdoptionRequest(
                (1,),
                f"adoption {index}",
                ("a.py",),
                f"2031-01-01T00:00:0{index}.000Z",
            )
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(adopt, range(4)))

    records = backend.factory(tmp_path).event_log().state.adoptions
    assert len(records) == 4
    assert len({record.event_id for record in records}) == 4
    assert all(record.item_event_ids == [item.event_id] for record in records)


def test_import_is_idempotent_conflicting_and_dry_run_is_read_only(
    store: FrictionRepository, backend: Backend, tmp_path: Path
) -> None:
    entry = FrictionImportEntry(
        "imported", "Imported", "session", created_at="2026-01-01T00:00:00.000Z"
    )
    before = store.version()
    result = store.import_entries([entry], dry_run=True)
    assert result.imported == 0 and result.would_import == 1 and result.dry_run
    assert store.version() == before
    assert backend.read_log(tmp_path) == b""
    assert store.import_entries([entry]).imported == 1
    duplicate = FrictionImportEntry("imported", "Changed", "session")
    assert store.import_entries([duplicate]).skipped == 1
    existing_dry_run = store.import_entries([duplicate], dry_run=True)
    assert existing_dry_run.would_import == 1
    assert existing_dry_run.skipped == 0
    assert store.version() != before
    conflict = FrictionImportEntry(
        "other",
        "Other",
        "session",
        occurrences=(
            LogOccurrence(
                "occurrence-1",
                "item",
                "2026-01-02T00:00:00.000Z",
                "/repo",
                "/repo",
                None,
                "evidence",
                None,
                {"incident_key": "same"},
            ),
            LogOccurrence(
                "occurrence-2",
                "item",
                "2026-01-02T00:00:00.000Z",
                "/repo",
                "/repo",
                None,
                "evidence",
                None,
                {"incident_key": "same"},
            ),
        ),
    )
    with pytest.raises(Conflict):
        store.import_entries([conflict])


def test_stable_identity_torn_tail_and_append_only(
    store: FrictionRepository, backend: Backend, tmp_path: Path
) -> None:
    if not backend.torn_tails:
        pytest.skip("rows commit whole; a torn tail cannot exist")
    first = add(store)
    log = backend.log_path(tmp_path)
    prefix = log.read_bytes()
    assert store.list_items().items[0].slug == first.slug
    assert log.read_bytes() == prefix
    rebuilt = backend.factory(tmp_path)
    assert rebuilt.list_items().items[0] == first
    with log.open("ab") as stream:
        stream.write(b'{"torn":')
    torn = log.read_bytes()
    complete_prefix = torn[: torn.rfind(b"\n") + 1]
    assert len(replay(log).events) == 2
    assert store.list_items().total == 1
    assert store.show(first.slug).occurrences.total == 1
    store.import_entries([FrictionImportEntry("next", "Next", "s")])
    appended = log.read_bytes()
    assert appended.startswith(complete_prefix)
    assert not appended.startswith(torn)
    assert replay(log).torn_line is None


def test_event_log_exposes_ordered_lines_fold_and_torn_tail(
    store: FrictionRepository, backend: Backend, tmp_path: Path
) -> None:
    if not backend.torn_tails:
        pytest.skip("rows commit whole; a torn tail cannot exist")
    first = add(store, "First")
    second = add(store, "Second")
    log = backend.log_path(tmp_path)
    complete = log.read_bytes()
    lines = complete.splitlines(keepends=True)
    expected_ids = tuple(event.id for event in replay(log).events)
    # Valid JSON whitespace is retained byte-for-byte by the repository read.
    log.write_bytes(lines[0][:-1] + b" \t\n" + b"".join(lines[1:]) + b'{"torn":')

    result = store.event_log()

    assert tuple(event.id for event in result.events) == expected_ids
    assert tuple(item.event_id for item in result.state.items) == (
        first.event_id,
        second.event_id,
    )
    log_bytes = log.read_bytes()
    complete_bytes = log_bytes[: log_bytes.rfind(b"\n") + 1]
    assert b"".join(line.encode("utf-8") for line in result.lines) == complete_bytes
    assert result.lines[0].endswith(" \t\n")
    assert result.torn_tail == '{"torn":'
    assert result.grouped_occurrences[first.event_id]


def test_event_log_is_empty_for_missing_store(store: FrictionRepository) -> None:
    result = store.event_log()

    assert result.events == ()
    assert result.lines == ()
    assert result.torn_tail == ""
    assert result.state.items == []
    assert result.grouped_occurrences == {}


def test_concurrent_append_and_version(
    store: FrictionRepository, backend: Backend, tmp_path: Path
) -> None:
    barrier = Barrier(8)

    def write(index: int) -> None:
        barrier.wait()
        backend.factory(tmp_path).import_entries(
            [FrictionImportEntry(f"item-{index}", f"Item {index}", "thread")]
        )

    before = store.version()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(8)))
    assert len(store.list_items().items) == 8
    assert store.version() != before


def test_concurrent_same_slug_import_has_one_winner(
    backend: Backend, tmp_path: Path
) -> None:
    barrier = Barrier(8)

    def write(_: int) -> int:
        barrier.wait()
        return (
            backend.factory(tmp_path)
            .import_entries([FrictionImportEntry("same", "Same", "thread")])
            .imported
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(write, range(8)))
    assert sum(results) == 1
    assert len(backend.factory(tmp_path).list_items().items) == 1


def test_batch_item_and_occurrence_events_are_adjacent(
    backend: Backend, tmp_path: Path
) -> None:
    store = backend.factory(tmp_path)
    store.add(FrictionAddRequest("Batch", "s", "evidence", "/work", "/repo"))
    events = backend.events(tmp_path)
    assert [event.kind for event in events] == ["item_added", "occurrence_appended"]


def test_concurrent_process_appenders(tmp_path: Path, backend: Backend) -> None:
    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(
            target=_process_append, args=(str(tmp_path), backend.name, "same")
        )
        for index in range(4)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)
        assert not worker.is_alive(), "append worker did not finish"
        assert worker.exitcode == 0
    store = backend.factory(tmp_path)
    assert len(store.list_items().items) == 1


def test_unknown_historical_item_does_not_append(
    store: FrictionRepository, backend: Backend, tmp_path: Path
) -> None:
    from varde_data.errors import NotFound

    before = backend.read_log(tmp_path)
    request = HistoricalCaptureRequest(
        HistoricalItemMode.append(999),
        HistoricalOccurrenceRequest(
            "2033-01-01T00:00:00.000Z",
            "/work",
            None,
            None,
            "evidence",
            {"event": {}},
            HistoricalWitness(
                "codex", "thread", "kind", "id", "source", 0, 0, 1, "c" * 64
            ),
        ),
    )
    with pytest.raises(NotFound):
        store.record_historical(request)
    after = backend.read_log(tmp_path)
    assert after == before


def test_version_changes_for_each_write(
    store: FrictionRepository, backend: Backend, tmp_path: Path
) -> None:
    before = store.version()
    item = add(store)
    assert store.version() != before
    prefix = backend.read_log(tmp_path)
    before = store.version()
    store.set_status(FrictionStatusRequest(item.event_id, "resolved", "fixed"))
    assert store.version() != before
    assert backend.read_log(tmp_path).startswith(prefix)
    prefix = backend.read_log(tmp_path)
    before = store.version()
    store.record_adoption(
        AdoptionRequest((1,), "adopted", ("file.py",), "2032-01-01T00:00:00.000Z")
    )
    assert store.version() != before
    assert backend.read_log(tmp_path).startswith(prefix)
    prefix = backend.read_log(tmp_path)
    before = store.version()
    entry = FrictionImportEntry("imported", "Imported", "session")
    store.import_entries([entry])
    assert store.version() != before
    assert backend.read_log(tmp_path).startswith(prefix)
    before = store.version()
    prefix = backend.read_log(tmp_path)
    store.import_entries([entry])
    assert store.version() == before
    assert backend.read_log(tmp_path) == prefix


def test_historical_witness_and_idempotent_record(store: FrictionRepository) -> None:
    add(store)
    event = HistoricalCaptureRequest(
        HistoricalItemMode.append(1),
        HistoricalOccurrenceRequest(
            "2033-01-01T00:00:00.000Z",
            "/work",
            "/repo",
            None,
            "captured evidence",
            {"event": {"summary": "captured"}},
            HistoricalWitness(
                "codex",
                "thread-1",
                "friction",
                "witness-1",
                "source",
                0,
                0,
                1,
                "b" * 64,
            ),
        ),
    )
    first = store.record_historical(event)
    second = store.record_historical(event)
    assert first.created is True
    assert second.created is False
    assert store.find_historical_witness(
        harness="codex", thread_id="thread-1", witness_id="witness-1"
    )


def test_import_events_reports_dry_run_and_present_events(
    store: FrictionRepository,
) -> None:
    event = Event.at(
        "2026-01-01T00:00:00.000Z",
        None,
        ItemAdded("Event", "s"),
        pid=2,
        counter=1,
    )
    planned = store.import_events([event], dry_run=True)
    assert planned.dry_run and planned.imported == 0 and planned.present == 0
    assert store.list_items().total == 0
    inserted = store.import_events([event])
    assert inserted.imported == 1 and inserted.present == 0
    repeated = store.import_events([event], dry_run=True)
    assert repeated.present == 1 and repeated.imported == 0
    assert store.import_events([event]).present == 1


def test_historical_create_and_fallback_witness(store: FrictionRepository) -> None:
    request = HistoricalCaptureRequest(
        HistoricalItemMode.create("session", "Created historical", "target", "/repo"),
        HistoricalOccurrenceRequest(
            "2033-01-01T00:00:00.000Z",
            "/work",
            "/repo",
            None,
            "captured",
            {"event": {}},
            HistoricalWitness(
                "codex", "thread-fallback", "kind", None, "source", 5, 10, 20, "d" * 64
            ),
        ),
    )
    created = store.record_historical(request)
    assert created.created and created.item.title == "Created historical"
    assert store.find_historical_fallback_witness(
        harness="codex",
        thread_id="thread-fallback",
        record_index=5,
        record_digest="d" * 64,
    )
    repeated = store.record_historical(request)
    assert (
        not repeated.created
        and repeated.occurrence.event_id == created.occurrence.event_id
    )
    conflict_request = HistoricalCaptureRequest(
        request.mode,
        HistoricalOccurrenceRequest(
            request.occurrence.at,
            request.occurrence.cwd,
            request.occurrence.repo_root,
            request.occurrence.head_sha,
            "changed evidence",
            request.occurrence.canonical_facts,
            request.occurrence.witness,
        ),
    )
    with pytest.raises(Conflict):
        store.record_historical(conflict_request)


def test_same_incident_key_race_has_one_winner(
    backend: Backend, tmp_path: Path
) -> None:
    barrier = Barrier(8)
    request = HistoricalCaptureRequest(
        HistoricalItemMode.create("session", "Raced", None, "/repo"),
        HistoricalOccurrenceRequest(
            "2035-01-01T00:00:00.000Z",
            "/work",
            "/repo",
            None,
            "captured",
            {"event": {}},
            HistoricalWitness(
                "codex", "race-thread", "kind", "native-id", "source", 0, 0, 1, "e" * 64
            ),
        ),
    )

    def capture(_: int) -> bool:
        barrier.wait()
        return backend.factory(tmp_path).record_historical(request).created

    with ThreadPoolExecutor(max_workers=8) as pool:
        created = list(pool.map(capture, range(8)))
    assert sum(created) == 1
    assert backend.factory(tmp_path).list_items().total == 1


def test_recurrence_uses_latest_prior_adoption(store: FrictionRepository) -> None:
    add(store)
    store.record_adoption(
        AdoptionRequest((1,), "first", ("a.py",), "2036-01-01T00:00:00.000Z")
    )
    store.record_adoption(
        AdoptionRequest((1,), "latest", ("b.py",), "2036-01-03T00:00:00.000Z")
    )
    capture = HistoricalCaptureRequest(
        HistoricalItemMode.append(1),
        HistoricalOccurrenceRequest(
            "2036-01-04T00:00:00.000Z",
            "/work",
            "/repo",
            None,
            "again",
            {"event": {}},
            HistoricalWitness(
                "codex",
                "latest-thread",
                "kind",
                "latest-id",
                "source",
                0,
                0,
                1,
                "f" * 64,
            ),
        ),
    )
    store.record_historical(capture)
    report = store.list_recurrences()
    assert report.page.total == 1
    assert report.page.items[0].adoption.summary == "latest"


def test_import_uses_entry_slug_independent_of_title(store: FrictionRepository) -> None:
    entry = FrictionImportEntry("stored-slug", "A different title", "session")
    assert store.import_entries([entry]).imported == 1
    assert store.import_entries([entry]).skipped == 1
    assert store.list_items().items[0].slug != "a-different-title"


def test_import_preserves_legacy_numeric_ids(store: FrictionRepository) -> None:
    from varde_data.records.friction import LogStatusChange

    entry = FrictionImportEntry(
        "legacy",
        "Legacy",
        "session",
        id=91,
        occurrences=(
            LogOccurrence(
                "92",
                "legacy",
                "2026-01-01T00:00:00.000Z",
                "/work",
                None,
                None,
                "evidence",
                None,
                None,
            ),
        ),
        status_changes=(
            LogStatusChange(
                "93", "legacy", "2026-01-02T00:00:00.000Z", "open", "resolved", "fixed"
            ),
        ),
    )
    result = store.import_entries([entry])
    assert result.id_map is not None
    assert list(result.id_map["items"].values()) == [91]
    assert list(result.id_map["occurrences"].values()) == [92]
    assert list(result.id_map["status_changes"].values()) == [93]


def test_event_log_lines_are_valid_json(
    store: FrictionRepository, backend: Backend, tmp_path: Path
) -> None:
    add(store)
    rows = backend.read_log(tmp_path).decode().splitlines()
    assert all(json.loads(row)["kind"] for row in rows)
