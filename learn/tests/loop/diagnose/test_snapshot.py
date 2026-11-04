from __future__ import annotations

import hashlib
import json
from pathlib import Path

from varde_learn.loop.diagnose.capture import load_snapshot
from varde_learn.loop.diagnose.snapshot import (
    apply_cutoff,
    snapshot_document,
    write_snapshot,
)


def _anchor(source_id: str, index: int, line: bytes, start: int) -> dict:
    return {
        "source_id": source_id,
        "record_index": index,
        "byte_start": start,
        "byte_end": start + len(line),
        "record_digest": "sha256:" + hashlib.sha256(line).hexdigest(),
        "native_id": None,
    }


def test_rfc3339_cutoff_compares_nanosecond_instants_without_precision_loss(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "rollout.jsonl"
    lines = [
        b'{"type":"session_meta","payload":{"id":"root","cli_version":"0.155.1"}}',
        b'{"timestamp":"2026-10-06T10:00:00.000000001Z","type":"response_item","payload":{"type":"message"}}',
    ]
    raw = b"\n".join(lines) + b"\n"
    source_path.write_bytes(raw)
    source_id = str(source_path.resolve())
    cutoff = _anchor(source_id, 1, lines[1], len(lines[0]) + 1)
    source = {
        "source_id": source_id,
        "canonical_path": source_id,
        "harness": "codex",
        "format": "codex-jsonl",
        "initial_length": len(raw),
        "captured_length": len(raw),
        "device": source_path.stat().st_dev,
        "inode": source_path.stat().st_ino,
        "prefix_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }
    child_source = {
        **source,
        "source_id": "child-source",
        "canonical_path": "child-source",
    }
    snapshot = {
        "schema_version": 1,
        "digest": "",
        "session": {"harness": "codex", "thread_id": "root"},
        "children": [
            {
                "thread_id": "child",
                "source_id": "child-source",
                "started_at": "2026-10-06T10:00:00.000000002Z",
            }
        ],
        "sources": [source, child_source],
        "records": [
            {
                "session_thread_id": "root",
                "anchor": cutoff,
                "timestamp": "2026-10-06T10:00:00.000000001Z",
            },
            {
                "session_thread_id": "child",
                "anchor": {"source_id": "child-source", "record_index": 0},
                "timestamp": "2026-10-06T10:00:00.000000002Z",
            },
        ],
        "overlap": "current",
        "coverage": {
            "complete": False,
            "source_complete": True,
            "analysis_ready": False,
            "cutoff_verified": False,
            "cutoff_anchor": None,
            "omitted_records": 0,
            "record_count": 2,
            "warnings": [],
        },
        "snapshot": {"digest": ""},
    }
    cutoff_path = tmp_path / "cutoff.json"
    cutoff_path.write_text(
        json.dumps({"source_path": source_id, "record_anchor": cutoff})
    )
    apply_cutoff(snapshot, cutoff_path)
    assert snapshot["children"] == []
    assert [record["session_thread_id"] for record in snapshot["records"]] == ["root"]
    assert snapshot["coverage"]["cutoff_verified"]


def test_legacy_claude_snapshot_without_identity_fields_validates(
    tmp_path: Path,
) -> None:
    value = {
        "schema_version": 1,
        "digest": "",
        "session": {"harness": "claude", "thread_id": "session"},
        "children": [],
        "sources": [],
        "records": [],
        "overlap": "not_current",
        "coverage": {"complete": True},
        "redacted": 0,
    }
    value["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(value, separators=(",", ":")))
    assert load_snapshot(path)["session"] == {
        "harness": "claude",
        "thread_id": "session",
    }


def test_snapshot_round_trip_and_legacy_length_migration(tmp_path: Path) -> None:
    value = {
        "session": {"harness": "claude", "thread_id": "session"},
        "children": [],
        "sources": [],
        "records": [{"tool_output_length_bytes": 5000}],
        "overlap": "not_current",
        "coverage": {"complete": True},
    }
    path = tmp_path / "snapshot.json"
    document = snapshot_document(value)
    assert document["schema_version"] == 2
    write_snapshot(path, document)
    assert load_snapshot(path)["records"][0]["tool_output_length_bytes"] == 5000

    old = dict(document)
    old["schema_version"] = 1
    old["records"] = [{}]
    old["digest"] = ""
    old["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(old, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    path.write_text(json.dumps(old, separators=(",", ":")))
    migrated = load_snapshot(path)
    assert migrated["records"][0]["tool_output_length_bytes"] is None
    assert migrated["schema_version"] == 1
    assert migrated["digest"] == old["digest"]
