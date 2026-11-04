from __future__ import annotations

import io
import json
from dataclasses import replace
from types import SimpleNamespace

from varde_data import friction_events
from varde_data.friction_events import fold
from varde_learn.loop import cli_friction
from varde_learn.loop.friction_repository import open_repository


def _run(monkeypatch, store, *args):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    output = SimpleNamespace(stdout=io.StringIO(), stderr=io.StringIO())
    assert cli_friction.run(["friction", *args], output) == 0, output.stderr.getvalue()
    return output.stdout.getvalue()


def _export(monkeypatch, store, destination):
    return _run(monkeypatch, store, "export", "--md", "--out", str(destination))


def _state_by_event(store):
    state = open_repository(store).event_log().state
    return {
        "items": sorted(
            (item.event_id, item.title, item.status, item.source)
            for item in state.items
        ),
        "occurrences": sorted(
            (item.event_id, item.item_event_id, item.evidence)
            for item in state.occurrences
        ),
        "status_changes": sorted(
            (item.event_id, item.item_event_id, item.to)
            for item in state.status_changes
        ),
        "adoptions": sorted((item.event_id, item.summary) for item in state.adoptions),
    }


def test_markdown_event_export_round_trips_to_empty_store(tmp_path, monkeypatch):
    source = tmp_path / "source"
    _run(
        monkeypatch,
        source,
        "add",
        "--source",
        "pytest",
        "--title",
        "Slow tests",
        "--text",
        "Test evidence",
    )
    before = _run(monkeypatch, source, "list")
    exported = tmp_path / "friction.md"
    _export(monkeypatch, source, exported)

    target = tmp_path / "target"
    _run(monkeypatch, target, "import", str(exported))

    assert _run(monkeypatch, target, "list") == before


def test_markdown_event_import_is_idempotent(tmp_path, monkeypatch):
    source = tmp_path / "source"
    _run(
        monkeypatch,
        source,
        "add",
        "--source",
        "pytest",
        "--title",
        "Slow tests",
        "--text",
        "Test evidence",
    )
    exported = tmp_path / "friction.md"
    _export(monkeypatch, source, exported)
    target = tmp_path / "target"

    _run(monkeypatch, target, "import", str(exported))
    first = (target / "friction.jsonl").read_bytes()
    _run(monkeypatch, target, "import", str(exported))

    assert (target / "friction.jsonl").read_bytes() == first


def _bundle(path, event_id, timestamp, title):
    event = {
        "v": 1,
        "id": event_id,
        "ts": timestamp,
        "kind": "item_added",
        "body": {"title": title, "source": "test"},
    }
    path.write_text(
        f"# Export\n\n## open\n\n### {title}\n```jsonl\n"
        + json.dumps(event, separators=(",", ":"))
        + "\n```\n",
        encoding="utf-8",
    )
    return event


def test_markdown_event_import_union_is_order_independent(tmp_path, monkeypatch):
    bundle_a, bundle_b = tmp_path / "a.md", tmp_path / "b.md"
    _bundle(bundle_a, "0000000000000001", "2025-01-01T00:00:00.000Z", "Alpha")
    _bundle(bundle_b, "0000000000000002", "2025-01-02T00:00:00.000Z", "Beta")
    left, right = tmp_path / "left", tmp_path / "right"
    _run(monkeypatch, left, "import", str(bundle_a))
    _run(monkeypatch, left, "import", str(bundle_b))
    _run(monkeypatch, right, "import", str(bundle_b))
    _run(monkeypatch, right, "import", str(bundle_a))

    assert _state_by_event(left) == _state_by_event(right)


def test_markdown_event_import_rejects_conflicting_payload(tmp_path, monkeypatch):
    original, conflict = tmp_path / "original.md", tmp_path / "conflict.md"
    event = _bundle(original, "0000000000000001", "2025-01-01T00:00:00.000Z", "Alpha")
    event["body"]["title"] = "Different payload"
    conflict.write_text(
        "```jsonl\n" + json.dumps(event, separators=(",", ":")) + "\n```\n",
        encoding="utf-8",
    )
    store = tmp_path / "store"
    _run(monkeypatch, store, "import", str(original))
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    output = SimpleNamespace(stdout=io.StringIO(), stderr=io.StringIO())

    assert cli_friction.run(["friction", "import", str(conflict)], output) != 0
    assert "conflicting payload" in output.stderr.getvalue()


def _run_any(monkeypatch, store, args):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    output = SimpleNamespace(stdout=io.StringIO(), stderr=io.StringIO())
    code = cli_friction.run(args, output)
    return code, output.stdout.getvalue(), output.stderr.getvalue()


def test_dry_run_validates_without_writing_store(tmp_path, monkeypatch):
    bundle = tmp_path / "events.md"
    _bundle(bundle, "0000000000000001", "2025-01-01T00:00:00.000Z", "Alpha")
    store = tmp_path / "store"

    code, out, err = _run_any(
        monkeypatch, store, ["friction", "import", "--dry-run", str(bundle)]
    )

    assert code == 0, err
    assert "Would import 1 new" in out
    assert not store.exists()


def test_import_rejects_bad_fields_and_oversized_events_without_appending(
    tmp_path, monkeypatch
):
    event = _bundle(
        tmp_path / "seed.md", "0000000000000001", "2025-01-01T00:00:00.000Z", "Alpha"
    )
    invalid = tmp_path / "invalid.md"
    store = tmp_path / "store"
    for timestamp in (5, "garbage"):
        event["ts"] = timestamp
        invalid.write_text(
            "```jsonl\n" + json.dumps(event) + "\n```\n", encoding="utf-8"
        )
        code, _, err = _run_any(
            monkeypatch, store, ["friction", "import", str(invalid)]
        )
        assert code != 0
        assert "timestamp" in err
        assert not (store / "friction.jsonl").exists()

    event["ts"] = "2025-01-01T00:00:00.000Z"
    event["body"]["title"] = 42
    invalid.write_text("```jsonl\n" + json.dumps(event) + "\n```\n", encoding="utf-8")
    code, _, err = _run_any(monkeypatch, store, ["friction", "import", str(invalid)])
    assert code != 0
    assert "title" in err
    assert not (store / "friction.jsonl").exists()

    event["body"]["title"] = "x" * (1024 * 1024)
    invalid.write_text("```jsonl\n" + json.dumps(event) + "\n```\n", encoding="utf-8")
    code, _, err = _run_any(monkeypatch, store, ["friction", "import", str(invalid)])
    assert code != 0
    assert "exceeds" in err
    assert not (store / "friction.jsonl").exists()


def test_import_temp_rebuild_failure_leaves_event_log_empty(tmp_path, monkeypatch):
    item = {
        "v": 1,
        "id": "0000000000000001",
        "ts": "2025-01-01T00:00:00.000Z",
        "kind": "item_added",
        "body": {"title": "Alpha", "source": "test"},
    }
    occurrence = {
        "v": 1,
        "id": "0000000000000002",
        "ts": "2025-01-01T00:00:01.000Z",
        "kind": "occurrence_appended",
        "body": {
            "item": item["id"],
            "at": "2025-01-01T00:00:01.000Z",
            "cwd": "/tmp",  # noqa: S108 - Fixture models an exported absolute cwd.
            "evidence": "evidence",
            "provenance": {"incident_key": "incomplete"},
        },
    }
    bundle = tmp_path / "invalid-rebuild.md"
    bundle.write_text(
        "```jsonl\n" + json.dumps(item) + "\n" + json.dumps(occurrence) + "\n```\n",
        encoding="utf-8",
    )
    store = tmp_path / "store"

    code, _, _ = _run_any(monkeypatch, store, ["friction", "import", str(bundle)])

    assert code != 0
    assert (store / "friction.jsonl").read_bytes() == b""


def test_import_repairs_torn_tail_before_appending(tmp_path, monkeypatch):
    store = tmp_path / "store"
    _run(
        monkeypatch,
        store,
        "add",
        "--source",
        "test",
        "--title",
        "Local",
        "--text",
        "proof",
    )
    log_path = store / "friction.jsonl"
    log_path.write_bytes(log_path.read_bytes() + b'{"v":1,"id":"broken')
    bundle = tmp_path / "event.md"
    _bundle(bundle, "0000000000000002", "2025-01-02T00:00:00.000Z", "Remote")

    _run(monkeypatch, store, "import", str(bundle))

    assert len(open_repository(store).event_log().events) == 3
    assert log_path.read_bytes().endswith(b"\n")


def test_uppercase_event_id_is_rejected(tmp_path, monkeypatch):
    bundle = tmp_path / "upper.md"
    _bundle(bundle, "000000000000000A", "2025-01-01T00:00:00.000Z", "Alpha")
    store = tmp_path / "store"

    code, _, err = _run_any(monkeypatch, store, ["friction", "import", str(bundle)])

    assert code != 0
    assert "invalid friction event id" in err
    assert not (store / "friction.jsonl").exists()


def test_directory_import_routing_supports_repository_equals_form(
    tmp_path, monkeypatch
):
    directory = tmp_path / "imports"
    directory.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    store = tmp_path / "store"
    code, _, err = _run_any(
        monkeypatch,
        store,
        ["friction", "import", f"--repository={repo}", str(directory)],
    )
    assert code == 0, err

    code, _, err = _run_any(monkeypatch, store, ["friction", "import", str(directory)])
    assert code == 2
    assert "--repository is required" in err


def test_import_keeps_existing_local_item_ids_and_reports_counts(tmp_path, monkeypatch):
    store = tmp_path / "store"
    _run(
        monkeypatch,
        store,
        "add",
        "--source",
        "test",
        "--title",
        "Local",
        "--text",
        "proof",
    )
    bundle = tmp_path / "remote.md"
    _bundle(bundle, "0000000000000001", "2024-01-01T00:00:00.000Z", "Remote")

    first = _run(monkeypatch, store, "import", str(bundle))
    second = _run(monkeypatch, store, "import", str(bundle))
    listing = _run(monkeypatch, store, "list")

    assert "Imported 1 new" in first
    assert "0 already present" in first
    assert "0 new" in second and "1 already present" in second
    assert listing.startswith("1 local")
    assert "2 remote" in listing


def test_export_stdout_preserves_lines_and_sanitizes_multiline_headings(
    tmp_path, monkeypatch
):
    store = tmp_path / "store"
    title = "Beta\n## open\n### forged"
    _run(
        monkeypatch,
        store,
        "add",
        "--source",
        "test",
        "--title",
        title,
        "--text",
        "proof",
    )

    markdown = _run(monkeypatch, store, "export", "--md")

    assert "### Beta ## open ### forged (" in markdown
    assert "\n### forged\n" not in markdown
    assert "```jsonl\n\n" not in markdown


def test_export_handles_unknown_folded_status_without_key_error(tmp_path, monkeypatch):
    store = tmp_path / "store"
    _run(
        monkeypatch,
        store,
        "add",
        "--source",
        "test",
        "--title",
        "Alpha",
        "--text",
        "proof",
    )
    original_fold = fold

    def unknown_status(events):
        state = original_fold(events)
        return replace(state, items=[replace(state.items[0], status="future")])

    monkeypatch.setattr(friction_events, "fold", unknown_status)

    markdown = _run(monkeypatch, store, "export", "--md")

    assert "### Unattached events" in markdown


def test_export_import_round_trip_keeps_jsonl_bytes_and_status_adoption_events(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    _run(
        monkeypatch,
        source,
        "add",
        "--source",
        "test",
        "--title",
        "Alpha",
        "--text",
        "proof",
    )
    _run(monkeypatch, source, "set-status", "--reason", "fixed", "1", "resolved")
    code, _, err = _run_any(
        monkeypatch,
        source,
        ["adopt", "record", "--items", "1", "--summary", "Adopted", "--files", "a.py"],
    )
    assert code == 0, err
    original = (source / "friction.jsonl").read_bytes()
    target = tmp_path / "target"
    markdown = _run(monkeypatch, source, "export", "--md")
    bundle = tmp_path / "with-history.md"
    bundle.write_text(markdown, encoding="utf-8")

    _run(monkeypatch, target, "import", str(bundle))

    assert (target / "friction.jsonl").read_bytes() == original
    kinds = [event.kind for event in open_repository(target).event_log().events]
    assert "status_changed" in kinds
    assert "adoption_recorded" in kinds


def test_per_item_directory_export_still_writes_item_markdown(tmp_path, monkeypatch):
    store, directory = tmp_path / "store", tmp_path / "items"
    _run(
        monkeypatch,
        store,
        "add",
        "--source",
        "test",
        "--title",
        "Alpha",
        "--text",
        "proof",
    )

    _run(monkeypatch, store, "export", str(directory))

    files = list(directory.glob("*.md"))
    assert len(files) == 1
    assert 'format: "varde-friction-item"' in files[0].read_text(encoding="utf-8")
