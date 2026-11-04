from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import varde_data.friction_events as data_friction_events
from varde_learn.loop import cli_diagnose, cli_friction, cli_friction_write
from varde_learn.loop.diagnose import claude
from varde_learn.loop.diagnose.capture import load_snapshot
from varde_learn.loop.diagnose.snapshot import write_snapshot
from varde_learn.loop.store import types as store_types

GOLDENS = Path(__file__).parent / "golden" / "friction"


def _dump_database(path: Path, log_bytes: bytes) -> bytes:
    with sqlite3.connect(path) as db:
        tables = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        dump = {
            table: [
                list(row)
                for row in db.execute(
                    f'SELECT * FROM "{table}" ORDER BY rowid'  # noqa: S608 - table is enumerated from sqlite_master.
                )
            ]
            for table in tables
        }
    for row in dump["meta"]:
        if row[0] == "log_bytes":
            row[1] = str(len(log_bytes))
        elif row[0] == "log_hash":
            row[1] = hashlib.sha256(log_bytes).hexdigest()
    return (
        json.dumps(dump, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _capture(tmp_path: Path, monkeypatch, capsys) -> dict[str, bytes]:  # noqa: PLR0915
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    monkeypatch.chdir(tmp_path)
    now = datetime(2025, 1, 1, tzinfo=UTC)

    def timestamp():
        nonlocal now
        value = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        now += timedelta(seconds=1)
        return value

    monkeypatch.setattr(cli_friction_write.store_write, "now_timestamp", timestamp)
    event_counter = 0
    real_event_id = data_friction_events.event_id

    def deterministic_event_id(ts, kind, body, **_kwargs):
        nonlocal event_counter
        value = real_event_id(ts, kind, body, pid=1, counter=event_counter)
        event_counter += 1
        return value

    # Learn's event_id hook accepts deterministic pid/counter inputs while
    # retaining the production identity format (including both fields).
    monkeypatch.setattr(data_friction_events, "event_id", deterministic_event_id)
    real_path = cli_friction_write.Path

    class GoldenCwdPath:
        def __new__(cls, *args, **kwargs):
            return real_path(*args, **kwargs)

        @classmethod
        def cwd(cls):
            return real_path("/golden/work")

    monkeypatch.setattr(cli_friction_write, "Path", GoldenCwdPath)
    real_claude_snapshot = claude._snapshot

    def snapshot_with_stable_source_id(*args, **kwargs):
        snapshot = real_claude_snapshot(*args, **kwargs)
        source_id = "/golden/evidence.jsonl"
        for source in snapshot.sources:
            source.source_id = source_id
        for record in (*snapshot.records, *snapshot.usage_records):
            record.anchor.source_id = source_id
        return snapshot

    monkeypatch.setattr(claude, "_snapshot", snapshot_with_stable_source_id)
    monkeypatch.setattr(
        store_types,
        "repository_context",
        lambda _path: store_types.RepositoryContext("/repo", "abc"),
    )
    monkeypatch.chdir(tmp_path)
    from varde_learn.loop.store import write as store_write

    monkeypatch.setattr(
        store_write,
        "repository_context",
        lambda _path: store_types.RepositoryContext("/repo", "abc"),
    )
    outputs: dict[str, str] = {}

    def invoke(name: str, args: list[str]) -> int:
        out, err = StringIO(), StringIO()
        code = cli_friction.run(
            args, SimpleNamespace(stdout=out, stderr=err, stdin=StringIO())
        )
        outputs[name] = out.getvalue()
        outputs[name + ".stderr"] = err.getvalue()
        outputs[name + ".exit"] = f"{code}\n"
        return code

    assert (
        invoke(
            "add",
            [
                "friction",
                "add",
                "--source",
                "pytest",
                "--title",
                "Golden",
                "--target",
                "docs/guide.md",
                "--text",
                "first evidence",
                "--tag",
                "golden",
                "--json",
            ],
        )
        == 0
    ), outputs
    assert invoke("list", ["friction", "list", "--json"]) == 0
    assert invoke("show", ["friction", "show", "1", "--json"]) == 0
    assert (
        invoke(
            "status",
            ["friction", "set-status", "--reason", "fixed", "1", "resolved", "--json"],
        )
        == 0
    )
    assert (
        invoke(
            "adopt-record",
            [
                "adopt",
                "record",
                "--items",
                "1",
                "--summary",
                "Improve tests",
                "--files",
                "learn/test.py",
                "--json",
            ],
        )
        == 0
    )
    assert invoke("adopt-recurrence", ["adopt", "recurrence", "--json"]) == 0
    assert (
        invoke(
            "append", ["friction", "add", "--item", "1", "--text", "again", "--json"]
        )
        == 0
    )
    assert (
        invoke(
            "add-global",
            [
                "friction",
                "add",
                "--source",
                "pytest",
                "--title",
                "Global item",
                "--text",
                "global evidence",
                "--global",
                "--json",
            ],
        )
        == 0
    )
    export = tmp_path / "export"
    assert invoke("export", ["friction", "export", "--json", str(export)]) == 0
    duplicate = (
        (export / "golden.md")
        .read_text()
        .replace('title: "Golden"', 'title: "Conflicting Golden"')
    )
    (export / "golden-conflict.md").write_text(duplicate)
    assert (
        invoke(
            "import-dry-run",
            [
                "friction",
                "import",
                "--repository",
                "/repo",
                "--dry-run",
                "--json",
                str(export),
            ],
        )
        == 0
    )
    assert (
        invoke(
            "import-duplicate",
            ["friction", "import", "--repository", "/repo", "--json", str(export)],
        )
        == 0
    )
    assert (
        invoke(
            "import-conflict",
            ["friction", "import", "--repository", "/repo", "--json", str(export)],
        )
        == 0
    )

    # A clean destination demonstrates a successful entry import and that its
    # dry run leaves the destination untouched.
    success_export = tmp_path / "success-export"
    success_export.mkdir()
    (success_export / "golden.md").write_bytes((export / "golden.md").read_bytes())
    success_store = tmp_path / "success-store"
    monkeypatch.setenv("VARDE_LEARN_STORE", str(success_store))
    assert (
        invoke(
            "import-success-dry-run",
            [
                "friction",
                "import",
                "--repository",
                "/repo",
                "--dry-run",
                str(success_export),
            ],
        )
        == 0
    )
    assert not success_store.exists()
    outputs["import-success-dry-run.no-write"] = "no files written\n"
    assert (
        invoke(
            "import-success",
            ["friction", "import", "--repository", "/repo", str(success_export)],
        )
        == 0
    )
    outputs_bytes_extra = {
        "import-success.friction.jsonl": (success_store / "friction.jsonl").read_bytes()
    }

    # Portable event union export/import exercises the separate event path.
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    portable_path = tmp_path / "portable.md"
    assert (
        invoke(
            "export-md",
            ["friction", "export", "--md", "--out", str(portable_path)],
        )
        == 0
    )
    outputs_bytes_extra["portable-export.md"] = portable_path.read_bytes()
    portable_store = tmp_path / "portable-store"
    monkeypatch.setenv("VARDE_LEARN_STORE", str(portable_store))
    assert (
        invoke(
            "portable-import-dry-run",
            ["friction", "import", "--dry-run", str(portable_path)],
        )
        == 0
    )
    assert not portable_store.exists()
    outputs["portable-import-dry-run.no-write"] = "no files written\n"
    assert invoke("portable-import", ["friction", "import", str(portable_path)]) == 0
    outputs_bytes_extra["portable-import.friction.jsonl"] = (
        portable_store / "friction.jsonl"
    ).read_bytes()

    # Text output, representative list filters, and stable error exits.
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    assert invoke("list-text", ["friction", "list"]) == 0
    assert (
        invoke(
            "list-filter",
            [
                "friction",
                "list",
                "--source",
                "pytest",
                "--tag",
                "golden",
                "--offset",
                "0",
                "--limit",
                "1",
                "--text",
                "Golden",
            ],
        )
        == 0
    )
    assert invoke("list-global", ["friction", "list", "--global"]) == 0
    assert invoke("list-repository", ["friction", "list", "--repository", "/repo"]) == 0
    assert invoke("list-status", ["friction", "list", "--status", "resolved"]) == 0
    assert (
        invoke("list-page", ["friction", "list", "--offset", "1", "--limit", "1"]) == 0
    )
    assert invoke("show-text", ["friction", "show", "1"]) == 0
    additional_store = tmp_path / "additional-store"
    monkeypatch.setenv("VARDE_LEARN_STORE", str(additional_store))
    assert (
        invoke(
            "add-text",
            [
                "friction",
                "add",
                "--source",
                "pytest",
                "--title",
                "Text output",
                "--text",
                "plain evidence",
            ],
        )
        == 0
    )
    assert invoke("error-not-found", ["friction", "show", "missing", "--json"]) != 0
    assert (
        invoke(
            "error-invalid",
            ["friction", "set-status", "1", "broken", "--reason", "invalid", "--json"],
        )
        != 0
    )

    # The persisted log must contain a redaction marker and count, never the
    # secret itself.
    redaction_store = tmp_path / "redaction-store"
    monkeypatch.setenv("VARDE_LEARN_STORE", str(redaction_store))
    assert (
        invoke(
            "redaction",
            [
                "friction",
                "add",
                "--source",
                "pytest",
                "--title",
                "Redaction",
                "--text",
                "token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                "--json",
            ],
        )
        == 0
    )
    redacted_log = (redaction_store / "friction.jsonl").read_bytes()
    assert b"ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in redacted_log
    assert b'"redacted":1' in redacted_log
    outputs_bytes_extra["redacted.friction.jsonl"] = redacted_log

    # Append through the CLI after a deliberately torn final fragment.
    torn_store = tmp_path / "torn-store"
    torn_store.mkdir()
    (torn_store / "friction.jsonl").write_bytes(
        (store / "friction.jsonl").read_bytes() + b'{"v":1,"torn":'
    )
    monkeypatch.setenv("VARDE_LEARN_STORE", str(torn_store))
    assert (
        invoke(
            "torn-append",
            [
                "friction",
                "add",
                "--source",
                "pytest",
                "--title",
                "After torn tail",
                "--text",
                "recovered",
                "--json",
            ],
        )
        == 0
    )
    outputs_bytes_extra["torn-append.friction.jsonl"] = (
        torn_store / "friction.jsonl"
    ).read_bytes()
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    source = (
        GOLDENS
        / "claude-root"
        / "projects"
        / "repo"
        / "00000000-0000-4000-8000-000000000099.jsonl"
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(GOLDENS / "claude-root"))
    snapshot_path = tmp_path / "snapshot.json"
    inspect_out, inspect_err = StringIO(), StringIO()
    assert (
        cli_diagnose.run(
            [
                "diagnose",
                "inspect",
                "--harness",
                "claude",
                "--path",
                str(source),
                "--snapshot-out",
                str(snapshot_path),
                "--json",
            ],
            SimpleNamespace(stdout=inspect_out, stderr=inspect_err),
        )
        == 0
    )
    capsys.readouterr()
    snapshot = load_snapshot(snapshot_path)
    snapshot["overlap"] = "not_current"
    snapshot["coverage"]["cutoff_verified"] = True
    snapshot["digest"] = ""
    snapshot["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    write_snapshot(snapshot_path, snapshot)
    anchor = next(
        row
        for row in snapshot["records"]
        if row["anchor"].get("native_id") == "native-result"
    )
    capture_path = tmp_path / "capture.json"
    capture_path.write_text(
        json.dumps(
            {
                "snapshot_path": str(snapshot_path),
                "snapshot_digest": snapshot["digest"],
                "session_id": snapshot["session"]["thread_id"],
                "anchor": anchor["anchor"],
                "incident_kind": "failed-tool",
                "item": {
                    "mode": "new",
                    "source": "test",
                    "title": "Historical capture",
                },
                "evidence": "Historical capture evidence",
            }
        )
    )
    hist_out, hist_err = StringIO(), StringIO()
    assert (
        cli_diagnose.run(
            ["diagnose", "capture", "--file", str(capture_path), "--json"],
            SimpleNamespace(stdout=hist_out, stderr=hist_err),
        )
        == 0
    )
    outputs["historical-capture"] = capsys.readouterr().out
    outputs["historical-capture.exit"] = "0\n"
    log = (store / "friction.jsonl").read_bytes()
    outputs_bytes = {f"{key}.txt": value.encode() for key, value in outputs.items()}
    outputs_bytes["exported-item.md"] = (export / "golden.md").read_bytes()
    outputs_bytes["friction.jsonl"] = log
    outputs_bytes["learn.db.json"] = _dump_database(store / "learn.db", log)
    outputs_bytes.update(outputs_bytes_extra)
    return outputs_bytes


def test_friction_cli_goldens(tmp_path, monkeypatch, capsys):
    actual = _capture(tmp_path, monkeypatch, capsys)
    if __import__("os").environ.get("UPDATE_FRICTION_GOLDENS") == "1":
        GOLDENS.mkdir(parents=True, exist_ok=True)
        for name, value in actual.items():
            (GOLDENS / name).write_bytes(value)
    expected = {
        path.name: path.read_bytes() for path in GOLDENS.iterdir() if path.is_file()
    }
    assert actual == expected
