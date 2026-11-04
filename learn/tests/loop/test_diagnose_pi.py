from __future__ import annotations

import json
from pathlib import Path

from varde_learn.loop.diagnose.list import ListHarness, ListRequest, list_sessions
from varde_learn.loop.diagnose.metrics import session_metrics
from varde_learn.loop.diagnose.model import (
    HARNESS_ADAPTERS,
    DiagnosticHarness,
    harness_adapter,
)
from varde_learn.loop.diagnose.pi import PiHarness, inspect_path
from varde_learn.loop.errors import Diagnose

FIXTURES = Path(__file__).parent / "fixtures" / "pi"


def test_pi_v3_reads_all_entries_and_parent_session(tmp_path):
    path = tmp_path / "session.jsonl"
    lines = (FIXTURES / "session-v3.jsonl").read_text().splitlines()
    lines[0] = lines[0].replace("/repo/project", str(tmp_path))
    header = json.loads(lines[0])
    header["parentSession"] = "/sessions/20250101_parent-session-id.jsonl"
    lines[0] = json.dumps(header)
    path.write_text("\n".join(lines) + "\n")
    snapshot = inspect_path(path)
    assert len(snapshot.records) == 3
    assert snapshot.records[-1].kind == "branch_summary"
    assert snapshot.session.parent_thread_id == "pi:parent-session-id"
    assert "/sessions/20250101_parent-session-id.jsonl" in (
        snapshot.session.parent_provenance or ""
    )
    assert snapshot.records[0].parent_native_id is None
    assert snapshot.records[-1].parent_native_id == "a1b2c3d4"
    assert snapshot.records[-1].branch_from_id == "b2c3d4e5"
    assert snapshot.coverage.warnings[-1] == (
        "Pi parse stats: parsed 3, skipped 0 records"
    )


def test_pi_v2_is_skipped_as_unsupported(tmp_path):
    path = tmp_path / "old.jsonl"
    path.write_bytes((FIXTURES / "session-v2.jsonl").read_bytes())
    snapshot = inspect_path(path)
    assert snapshot.records == []
    assert snapshot.coverage.omitted_records == 0
    assert snapshot.coverage.skipped_records == 1
    assert not snapshot.coverage.complete
    assert "skipped: unsupported session version" in snapshot.coverage.warnings


def test_pi_unparseable_file_is_reported_as_unsupported(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text("not-json\n")
    snapshot = inspect_path(path)
    assert snapshot.records == []
    assert "skipped: unsupported session version" in snapshot.coverage.warnings
    assert (
        snapshot.coverage.warnings[-1] == "Pi parse stats: parsed 0, skipped 0 records"
    )


def test_pi_empty_file_does_not_invent_skipped_records(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    snapshot = inspect_path(path)
    assert snapshot.coverage.skipped_records == 0
    assert snapshot.coverage.omitted_records == 0
    assert (
        snapshot.coverage.warnings[-1] == "Pi parse stats: parsed 0, skipped 0 records"
    )


def test_pi_oversized_file_keeps_valid_edge_records_and_exact_tail_anchor(
    tmp_path, monkeypatch
):
    from varde_learn.loop.diagnose import pi

    monkeypatch.setattr(pi, "MAX_SOURCE_BYTES", 768)
    header = {
        "type": "session",
        "version": 3,
        "id": "oversized-session",
        "timestamp": "2026-10-22T09:00:00.000Z",
        "cwd": str(tmp_path),
    }
    first = {
        "type": "message",
        "id": "first-entry",
        "timestamp": "2026-10-22T09:00:01.000Z",
        "message": {"role": "user", "content": "first"},
    }
    middle = {
        "type": "message",
        "id": "middle-entry",
        "timestamp": "2026-10-22T09:00:02.000Z",
        "message": {"role": "user", "content": "x" * 700},
    }
    last = {
        "type": "message",
        "id": "last-entry",
        "timestamp": "2026-10-22T09:00:03.000Z",
        "message": {"role": "user", "content": "last"},
    }
    source_lines = [
        json.dumps(row, separators=(",", ":")) for row in (header, first, middle, last)
    ]
    raw = ("\n".join(source_lines) + "\n").encode()
    path = tmp_path / "oversized.jsonl"
    path.write_bytes(raw)

    snapshot = inspect_path(path)

    assert snapshot.coverage.truncated
    assert snapshot.coverage.malformed_records == 0
    assert [record.anchor.native_id for record in snapshot.records] == [
        "first-entry",
        "last-entry",
    ]
    tail_record = snapshot.records[-1]
    expected_line = source_lines[-1].encode()
    expected_start = raw.index(expected_line)
    assert tail_record.anchor.byte_start == expected_start
    assert tail_record.anchor.byte_end == expected_start + len(expected_line)
    assert tail_record.anchor.record_digest == pi._digest(expected_line)
    assert snapshot.sources[0].digest is None


def test_pi_discovery_maps_parent_and_reads_only_bounded_headers(tmp_path, monkeypatch):
    from varde_learn.loop.diagnose import pi

    repo = tmp_path / "repo"
    repo.mkdir()
    root = tmp_path / "pi-sessions"
    folder = root / "--repo--"
    folder.mkdir(parents=True)
    for name, cwd in (
        ("20240101_outside.jsonl", str(tmp_path / "outside")),
        ("20250101_child.jsonl", str(repo)),
        ("20250102_other.jsonl", str(repo)),
    ):
        header = {
            "type": "session",
            "version": 3,
            "id": Path(name).stem.split("_", 1)[1],
            "timestamp": "2026-10-22T09:00:00.000Z",
            "cwd": cwd,
            "parentSession": "/sessions/20250101_parent-id.jsonl",
        }
        (folder / name).write_text(json.dumps(header) + "\n" + "x" * 100_000)
    monkeypatch.setattr(pi, "MAX_DISCOVERY_FILES", 2)
    read_paths = []
    read_header = pi._read_header

    def count_header(path):
        read_paths.append(path)
        return read_header(path)

    monkeypatch.setattr(pi, "_read_header", count_header)
    sessions = PiHarness().discover(repo=repo, roots={"pi": root}, limit=10)
    assert len(read_paths) == 2
    assert len(sessions) == 1
    assert sessions[0]["kind"] == "main"
    assert sessions[0]["parent_identity"] == "pi:parent-id"


def test_pi_normalized_records_feed_session_metrics(tmp_path):
    path = tmp_path / "metrics.jsonl"
    entries = [
        {
            "type": "session",
            "version": 3,
            "id": "metrics-session",
            "timestamp": "2026-10-22T09:00:00.000Z",
            "cwd": str(tmp_path),
        },
        {
            "type": "message",
            "id": "call-entry",
            "parentId": None,
            "timestamp": "2026-10-22T09:00:01.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "toolCall",
                        "id": "call-1",
                        "name": "bash",
                        "arguments": {"command": "ls"},
                    }
                ],
                "usage": {"input": 12, "output": 4},
            },
        },
        {
            "type": "message",
            "id": "result-entry",
            "parentId": "call-entry",
            "timestamp": "2026-10-22T09:00:02.000Z",
            "message": {
                "role": "toolResult",
                "toolCallId": "call-1",
                "toolName": "bash",
                "content": [{"type": "text", "text": "listed files"}],
                "isError": False,
            },
        },
    ]
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
    snapshot = inspect_path(path)
    metrics = session_metrics(snapshot.records)
    assert metrics["model_calls"] == 1
    assert metrics["input_tokens"] == 12
    assert metrics["output_tokens"] == 4
    assert metrics["tool_calls"] == 1


def test_pi_dispatch_and_repo_listing_do_not_include_pi(capsys):
    assert harness_adapter("pi").harness is DiagnosticHarness.PI
    assert "pi" not in {item.value for item in ListHarness}
    from varde_learn.loop.cli_diagnose import run

    assert run(["diagnose"]) == 0
    help_output = capsys.readouterr().out.lower()
    assert "commands:" in help_output
    assert "inspect" in help_output
    assert "list" in help_output


def test_pi_inspect_accepts_the_adapter_request_shape(tmp_path):
    from types import SimpleNamespace

    path = tmp_path / "session.jsonl"
    path.write_bytes((FIXTURES / "session-v3.jsonl").read_bytes())
    inspected = harness_adapter("pi").inspect(SimpleNamespace(path=path))
    assert inspected.session.harness == "pi"
    assert len(inspected.records) == 3


def test_adding_pi_does_not_grow_sweep_listing_warnings(tmp_path, monkeypatch):

    repo = tmp_path / "repo"
    repo.mkdir()
    empty = tmp_path / "empty"
    empty.mkdir()
    request = ListRequest("all", repo, empty, empty, empty, limit=1)
    calls = []

    class PiFailure:
        harness = DiagnosticHarness.PI

        def discover(self, **kwargs):
            calls.append(kwargs)
            raise Diagnose("pi_discovery_failed", "sentinel Pi discovery warning")

        def inspect(self, request):
            raise AssertionError("not used")

    monkeypatch.setitem(HARNESS_ADAPTERS, DiagnosticHarness.PI, PiFailure())
    result = list_sessions(request)
    assert calls == []
    assert "sentinel Pi discovery warning" not in result.warnings
