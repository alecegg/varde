import json
from dataclasses import replace
from pathlib import Path

import pytest
from varde_data.errors import Invalid
from varde_data.friction import open_friction
from varde_data.friction_events import (
    append,
    event_id,
    event_to_dict,
    fold,
    fold_store,
    replay,
)
from varde_data.records.friction import (
    AdoptionRecorded,
    Event,
    ItemAdded,
    ItemTagsChanged,
    OccurrenceAppended,
    StatusChanged,
)

ROOT = Path(__file__).resolve().parents[2]
LEGACY_FIXTURES = ROOT / "data/tests/fixtures/friction-log"
REAL_SAMPLES = ROOT / "data/tests/fixtures/compat"


def _events() -> list[Event]:
    item = Event.at(
        "2026-01-01T00:00:00.000Z",
        "/repo",
        ItemAdded("Alpha friction", "session", tags=["one"]),
        pid=7,
        counter=0,
    )
    return [
        item,
        Event.at(
            "2026-01-01T00:00:01.000Z",
            "/repo",
            OccurrenceAppended(
                item.id,
                "2026-01-01T00:00:01.000Z",
                "/work",
                "again",
                provenance={"key": "value"},
            ),
            pid=7,
            counter=1,
        ),
        Event.at(
            "2026-01-01T00:00:02.000Z",
            "/repo",
            StatusChanged(
                item.id, "2026-01-01T00:00:02.000Z", "open", "resolved", "fixed"
            ),
            pid=7,
            counter=2,
        ),
        Event.at(
            "2026-01-01T00:00:03.000Z",
            "/repo",
            ItemTagsChanged(item.id, ["two"]),
            pid=7,
            counter=3,
        ),
        Event.at(
            "2026-01-01T00:00:04.000Z",
            "/repo",
            AdoptionRecorded(
                "2026-01-01T00:00:04.000Z", "adopted", ["a.py"], [item.id]
            ),
            pid=7,
            counter=4,
        ),
    ]


def test_fold_matches_legacy_fixture_for_every_event_kind():
    events = _events()
    state = fold(events)
    assert state == fold(list(reversed(events)))
    assert state.items[0].slug == "alpha-friction"
    assert state.items[0].status == "resolved"
    assert state.items[0].tags == ["one", "two"]
    assert state.occurrences[0].event_id == "6cb8ea722f7e8f27"
    assert state.status_changes[0].event_id == "769c1b2edf0b3c0a"
    assert state.adoptions[0].event_id == "1f7b813d3d91bd41"
    assert state.orphaned_events == 0


def test_fixture_vectors_preserve_event_ids():
    vectors = json.loads((LEGACY_FIXTURES / "vectors.json").read_text())
    constructors = {
        "item_added": lambda body: ItemAdded(**body),
        "occurrence_appended": lambda body: OccurrenceAppended(**body),
        "status_changed": lambda body: StatusChanged(
            body["item"], body["at"], body["from"], body["to"], body["reason"]
        ),
        "adoption_recorded": lambda body: AdoptionRecorded(**body),
    }
    for row in vectors:
        body = constructors[row["kind"]](row["body"])
        assert (
            event_id(
                row["ts"], row["kind"], body, pid=row["pid"], counter=row["counter"]
            )
            == row["id"]
        )


def test_replay_real_format_samples_and_torn_tail():
    complete = replay(REAL_SAMPLES / "store/friction.jsonl")
    torn = replay(REAL_SAMPLES / "store-torn-tail/friction.jsonl")
    assert [event.kind for event in complete.events] == [
        "item_added",
        "occurrence_appended",
    ]
    assert [event.kind for event in torn.events] == [
        "item_added",
        "occurrence_appended",
    ]
    assert torn.torn_line is not None
    for event in (*complete.events, *torn.events):
        event.validate()


def test_append_redacts_inputs_and_preserves_wire_shape(tmp_path):
    event = _events()[0]
    append(
        tmp_path,
        event,
        redact=lambda value: (value.replace("Alpha", "[safe]"), int("Alpha" in value)),
    )
    raw = (tmp_path / "friction.jsonl").read_text()
    wire = json.loads(raw)
    assert raw.endswith("\n")
    assert wire["body"]["title"] == "[safe] friction"
    assert wire["redacted"] == 1
    body = replay(tmp_path).events[0].body
    assert isinstance(body, ItemAdded)
    assert body.title == "[safe] friction"


def test_append_repairs_torn_tail_and_bootstraps_git_files(tmp_path):
    event = _events()[0]
    path = tmp_path / "friction.jsonl"
    append(tmp_path, event, redact=lambda value: (value, 0))
    valid = path.read_bytes()
    path.write_bytes(valid + b'{"torn":')
    second = Event.at(
        "2026-01-01T00:00:05.000Z",
        "/repo",
        ItemAdded("Second", "session"),
        pid=7,
        counter=5,
    )
    append(tmp_path, second, redact=lambda value: (value, 0))
    assert [row.id for row in replay(tmp_path).events] == [event.id, second.id]
    assert (
        path.read_bytes()
        == valid
        + json.dumps(
            event_to_dict(second), ensure_ascii=False, separators=(",", ":")
        ).encode()
        + b"\n"
    )
    assert "friction.jsonl merge=union" in (tmp_path / ".gitattributes").read_text()
    assert "learn.db.init.lock" in (tmp_path / ".gitignore").read_text()


def test_replay_accepts_paths_or_line_iterables_not_text():
    with pytest.raises(TypeError):
        replay('{"not":"a path"}')


def test_fold_store_groups_occurrences(tmp_path):
    for event in _events()[:2]:
        append(tmp_path, event, redact=lambda value: (value, 0))
    state, grouped = fold_store(tmp_path)
    assert grouped[state.items[0].event_id] == state.occurrences


def test_import_rejects_invalid_provenance_in_the_data_layer(tmp_path: Path) -> None:
    source = ROOT / "data/tests/golden/friction/friction.jsonl"
    occurrence = next(
        event.body
        for event in replay(source).events
        if isinstance(event.body, OccurrenceAppended) and event.body.provenance
    )
    provenance = dict(occurrence.provenance or {})
    provenance["payload_digest"] = "invalid"
    invalid = Event.at(
        "2026-01-02T00:00:00.000Z",
        None,
        replace(occurrence, provenance=provenance),
        pid=19,
        counter=0,
    )

    with pytest.raises(Invalid, match="incident provenance key or payload digest"):
        open_friction(tmp_path).import_events([invalid])

    log = tmp_path / "friction.jsonl"
    assert not log.exists() or log.read_bytes() == b""
