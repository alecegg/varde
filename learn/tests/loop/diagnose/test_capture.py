from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from varde_learn.loop.diagnose.capture import (
    CaptureError,
    CaptureFlags,
    capture,
    capture_from_flags,
)


def _snapshot(path: Path, monkeypatch) -> tuple[Path, list[dict]]:
    database = path / "opencode.db"
    from varde_learn.loop.diagnose.opencode import (
        MESSAGE_COLUMNS,
        OPENCODE_VERSION,
        SESSION_COLUMNS,
    )

    db = sqlite3.connect(database)
    session_types = {
        "time_created",
        "time_updated",
        "time_idle",
        "time_viewed",
        "time_compacting",
        "time_archived",
        "time_suspended",
        "resume_attempts",
    }
    message_types = {"seq", "time_created", "time_updated"}
    db.execute(
        "CREATE TABLE session_v2 ("
        + ",".join(
            f'"{name}" {"INTEGER" if name in session_types else "TEXT"}'
            for name in SESSION_COLUMNS
        )
        + ")"
    )
    db.execute(
        "CREATE TABLE session_message ("
        + ",".join(
            f'"{name}" {"INTEGER" if name in message_types else "TEXT"}'
            for name in MESSAGE_COLUMNS
        )
        + ")"
    )
    for session_id, parent_id, created in (
        ("ses_parent", None, 1_791_280_800_000),
        ("ses_child", "ses_parent", 1_791_280_860_000),
    ):
        db.execute(
            "INSERT INTO session_v2 "
            "(id,project_id,parent_id,directory,version,time_created) "
            "VALUES (?,?,?,?,?,?)",
            (session_id, "project", parent_id, "/repo", OPENCODE_VERSION, created),
        )
    for session_id, msg_id, seq, timestamp in (
        ("ses_parent", "msg_parent_tool", 2, 1_791_280_810_000),
        ("ses_child", "msg_child_tool", 2, 1_791_280_870_000),
    ):
        message = {
            "id": msg_id,
            "type": "assistant",
            "content": [
                {
                    "type": "tool",
                    "id": f"call-{msg_id}",
                    "name": "bash",
                    "state": {
                        "status": "error",
                        "input": {"command": "false"},
                        "content": "historical output",
                        "error": {"message": "permission denied"},
                    },
                }
            ],
            "time": {"created": timestamp},
        }
        db.execute(
            "INSERT INTO session_message "
            "(id,session_id,type,seq,time_created,time_updated,data) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                msg_id,
                session_id,
                "assistant",
                seq,
                timestamp,
                timestamp,
                json.dumps(message),
            ),
        )
    db.commit()
    db.close()
    monkeypatch.setenv("OPENCODE_DB", str(database))
    from varde_learn.loop.cli_diagnose import run
    from varde_learn.loop.diagnose.capture import load_snapshot
    from varde_learn.loop.diagnose.snapshot import write_snapshot

    frozen = path / "snapshot.json"
    assert (
        run(
            [
                "diagnose",
                "inspect",
                "--harness",
                "opencode",
                "--session",
                "ses_parent",
                "--snapshot-out",
                str(frozen),
                "--json",
            ]
        )
        == 0
    )
    snapshot = load_snapshot(frozen)
    snapshot["coverage"]["cutoff_verified"] = True
    snapshot["digest"] = ""
    snapshot["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    write_snapshot(frozen, snapshot)
    anchors = [
        record["anchor"]
        for record in snapshot["records"]
        if record["anchor"].get("native_id") in {"msg_parent_tool", "msg_child_tool"}
    ]
    return frozen, anchors


def _flags(
    snapshot: Path, anchor: dict, *, native_id: str | None = None
) -> CaptureFlags:
    return CaptureFlags(
        snapshot,
        anchor["source_id"],
        anchor["record_index"],
        native_id,
        "failed-tool",
        None,
        "learn",
        "Synthetic failure",
        None,
        "Observed failure",
    )


def test_opencode_capture_index_without_native_id_is_ambiguous(
    tmp_path: Path, monkeypatch
) -> None:
    snapshot, anchors = _snapshot(tmp_path, monkeypatch)
    with pytest.raises(CaptureError, match="more than one record"):
        capture_from_flags(_flags(snapshot, anchors[0]))


def test_opencode_capture_copies_full_sqlite_anchor_to_persist(
    tmp_path: Path, monkeypatch
) -> None:
    snapshot, anchors = _snapshot(tmp_path, monkeypatch)
    captured = {}

    def persist(request):
        captured.update(request)
        return {"disposition": "created"}

    result = capture_from_flags(
        _flags(snapshot, anchors[1], native_id="msg_child_tool"), persist=persist
    )
    assert result == {"disposition": "created"}
    assert captured["anchor"] == anchors[1]
    assert captured["source"]["format"] == "opencode-sqlite-2.0.12"
    assert (
        captured["record"]["anchor"]["context_digest"] == anchors[1]["context_digest"]
    )


def test_legacy_opencode_snapshot_with_tool_output_still_captures(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_learn.loop.diagnose.capture import load_snapshot
    from varde_learn.loop.diagnose.snapshot import write_snapshot

    snapshot_path, anchors = _snapshot(tmp_path, monkeypatch)
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["schema_version"] = 1
    for record in snapshot["records"]:
        record.pop("tool_output_length_bytes", None)
        for observation in record.get("tool_observations", []):
            observation.pop("output_length_bytes", None)
    snapshot["digest"] = ""
    snapshot["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    legacy_digest = snapshot["digest"]
    write_snapshot(snapshot_path, snapshot)
    assert load_snapshot(snapshot_path)["digest"] == legacy_digest

    result = capture_from_flags(
        _flags(snapshot_path, anchors[1], native_id="msg_child_tool"),
        persist=lambda _request: {"disposition": "created"},
    )

    assert result == {"disposition": "created"}


def test_capture_retries_preserve_native_fact_for_store_deduplication(
    tmp_path: Path, monkeypatch
) -> None:
    snapshot, anchors = _snapshot(tmp_path, monkeypatch)
    persisted = {}

    def persist(request):
        anchor = request["anchor"]
        key = (
            anchor["source_id"],
            anchor["session_id"],
            anchor["storage_sequence"],
            anchor["context_digest"],
        )
        return persisted.setdefault(
            key,
            {"item_id": 8, "occurrence_id": "occurrence-1", "disposition": "created"},
        )

    flags = _flags(snapshot, anchors[1], native_id="msg_child_tool")
    first = capture_from_flags(flags, persist=persist)
    second = capture_from_flags(flags, persist=persist)
    assert first == second
    assert first["item_id"] == 8


def test_capture_rejects_forged_codex_tool_projection_before_persist(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_learn.loop.cli_diagnose import run
    from varde_learn.loop.diagnose.capture import load_snapshot
    from varde_learn.loop.diagnose.snapshot import write_snapshot

    source = tmp_path / ".codex/sessions/2026/10/06/rollout-thread.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "thread",
                            "cli_version": "0.155.1",
                            "cwd": "/repo",
                        },
                    }
                ),
                json.dumps({"type": "turn_context", "payload": {"cwd": "/repo"}}),
                json.dumps(
                    {
                        "type": "response_item",
                        "timestamp": "2026-10-06T10:02:00Z",
                        "id": "native-tool",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "call",
                            "output": "ordinary output",
                        },
                    }
                ),
                "",
            ]
        )
    )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    snapshot_path = tmp_path / "forged.json"
    assert (
        run(
            [
                "diagnose",
                "inspect",
                "--harness",
                "codex",
                "--path",
                str(source),
                "--snapshot-out",
                str(snapshot_path),
                "--json",
            ]
        )
        == 0
    )
    snapshot = load_snapshot(snapshot_path)
    snapshot["overlap"] = "not_current"
    snapshot["coverage"]["cutoff_verified"] = True
    selected = next(
        record
        for record in snapshot["records"]
        if record["anchor"].get("native_id") == "native-tool"
    )
    request_path = tmp_path / "capture.json"

    def write_snapshot_and_request(record: dict) -> None:
        snapshot["digest"] = ""
        snapshot["digest"] = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False).encode()
            ).hexdigest()
        )
        write_snapshot(snapshot_path, snapshot)
        request_path.write_text(
            json.dumps(
                {
                    "snapshot_path": str(snapshot_path),
                    "snapshot_digest": snapshot["digest"],
                    "session_id": "thread",
                    "anchor": record["anchor"],
                    "incident_kind": "failed-tool",
                    "item": {"mode": "existing", "id": 1},
                    "evidence": "reviewed evidence",
                }
            )
        )

    # The same unmutated record is captured end to end in
    # `test_capture_e2e.test_cli_codex_capture_is_visible_in_friction_list`, so
    # the rejection below can only come from the forged fields.
    selected["tool_status"] = "failed"
    selected["tool_error"] = "invented failure"
    write_snapshot_and_request(selected)
    persisted = []
    with pytest.raises(CaptureError) as raised:
        capture(request_path, persist=lambda value: persisted.append(value) or {})
    assert raised.value.code == "diagnose_snapshot_invalid"
    assert "revalidated native record" in str(raised.value)
    assert persisted == []


def test_capture_rejects_forged_claude_failure_over_native_success(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_learn.loop.cli_diagnose import run
    from varde_learn.loop.diagnose.capture import load_snapshot
    from varde_learn.loop.diagnose.snapshot import write_snapshot

    project = tmp_path / ".claude/projects/project"
    project.mkdir(parents=True)
    session_id = "00000000-0000-4000-8000-000000000099"
    source = project / f"{session_id}.jsonl"
    source.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "tool-call",
                        "sessionId": session_id,
                        "timestamp": "2026-10-06T10:00:00Z",
                        "cwd": "/repo",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tool-success",
                                    "name": "Bash",
                                    "input": {"command": "true"},
                                }
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "native-success",
                        "parentUuid": "tool-call",
                        "sessionId": session_id,
                        "timestamp": "2026-10-06T10:01:00Z",
                        "cwd": "/repo",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "tool-success",
                                    "is_error": False,
                                    "content": "completed successfully",
                                }
                            ],
                        },
                    }
                ),
                "",
            ]
        )
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))
    snapshot_path = tmp_path / "forged-claude.json"
    assert (
        run(
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
            ]
        )
        == 0
    )
    snapshot = load_snapshot(snapshot_path)
    snapshot["overlap"] = "not_current"
    snapshot["coverage"]["cutoff_verified"] = True
    selected = next(
        record
        for record in snapshot["records"]
        if record["anchor"].get("native_id") == "native-success"
    )
    assert selected["tool_status"] == "success"
    selected["tool_status"] = "error"
    selected["tool_error"] = "invented native error"
    snapshot["digest"] = ""
    snapshot["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    write_snapshot(snapshot_path, snapshot)
    request_path = tmp_path / "capture-claude.json"
    request_path.write_text(
        json.dumps(
            {
                "snapshot_path": str(snapshot_path),
                "snapshot_digest": snapshot["digest"],
                "session_id": snapshot["session"]["thread_id"],
                "anchor": selected["anchor"],
                "incident_kind": "failed-tool",
                "item": {"mode": "existing", "id": 1},
                "evidence": "reviewed evidence",
            }
        )
    )
    with pytest.raises(CaptureError, match="frozen tool evidence") as raised:
        capture(request_path, persist=lambda _: {"item_id": 1})
    assert raised.value.code == "diagnose_snapshot_invalid"
