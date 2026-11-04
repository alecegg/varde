from __future__ import annotations

import hashlib
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from varde_learn.loop import cli_diagnose, cli_friction
from varde_learn.loop.diagnose.capture import load_snapshot
from varde_learn.loop.diagnose.snapshot import write_snapshot


def _reseal_snapshot(path: Path, snapshot: dict) -> None:
    """Recompute the snapshot digest after the test edits frozen evidence."""
    snapshot["digest"] = ""
    snapshot["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
    )
    write_snapshot(path, snapshot)


def test_cli_capture_is_visible_in_friction_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    session_id = "00000000-0000-4000-8000-000000000099"
    project = tmp_path / ".claude/projects/project"
    project.mkdir(parents=True)
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
                                    "id": "tool-1",
                                    "name": "Bash",
                                    "input": {"command": "false"},
                                }
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "native-result",
                        "parentUuid": "tool-call",
                        "sessionId": session_id,
                        "timestamp": "2026-10-06T10:01:00Z",
                        "cwd": "/repo",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "tool-1",
                                    "is_error": True,
                                    "content": "permission denied",
                                }
                            ],
                        },
                    }
                ),
                "",
            ]
        )
    )

    snapshot_path = tmp_path / "snapshot.json"
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
            ]
        )
        == 0
    )
    capsys.readouterr()
    snapshot = load_snapshot(snapshot_path)
    snapshot["overlap"] = "not_current"
    snapshot["coverage"]["cutoff_verified"] = True
    _reseal_snapshot(snapshot_path, snapshot)
    record = next(
        record
        for record in snapshot["records"]
        if record["anchor"].get("native_id") == "native-result"
    )

    request_file = tmp_path / "capture.json"
    request_file.write_text(
        json.dumps(
            {
                "snapshot_path": str(snapshot_path),
                "snapshot_digest": snapshot["digest"],
                "session_id": snapshot["session"]["thread_id"],
                "anchor": record["anchor"],
                "incident_kind": "failed-tool",
                "item": {"mode": "new", "source": "test", "title": "Capture seam"},
                "evidence": "capture workflow evidence",
            }
        )
    )
    assert (
        cli_diagnose.run(["diagnose", "capture", "--file", str(request_file), "--json"])
        == 0
    )
    captured = json.loads(capsys.readouterr().out)
    assert captured["ok"] is True
    assert captured["data"]["disposition"] == "created"

    output = StringIO()
    assert (
        cli_friction.run(
            ["friction", "list", "--json"],
            SimpleNamespace(stdout=output, stderr=StringIO()),
        )
        == 0
    )
    listed = json.loads(output.getvalue())
    assert listed["data"]["items"][0]["title"] == "Capture seam"


def test_cli_codex_capture_is_visible_in_friction_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    monkeypatch.chdir(tmp_path)

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
                            "output": "permission denied",
                        },
                    }
                ),
                "",
            ]
        )
    )

    snapshot_path = tmp_path / "codex-snapshot.json"
    assert (
        cli_diagnose.run(
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
    capsys.readouterr()
    snapshot = load_snapshot(snapshot_path)
    snapshot["overlap"] = "not_current"
    snapshot["coverage"]["cutoff_verified"] = True
    _reseal_snapshot(snapshot_path, snapshot)
    record = next(
        record
        for record in snapshot["records"]
        if record["anchor"].get("native_id") == "native-tool"
    )
    assert "tool_observations" not in record

    request_file = tmp_path / "codex-capture.json"
    request_file.write_text(
        json.dumps(
            {
                "snapshot_path": str(snapshot_path),
                "snapshot_digest": snapshot["digest"],
                "session_id": snapshot["session"]["thread_id"],
                "anchor": record["anchor"],
                "incident_kind": "failed-tool",
                "item": {"mode": "new", "source": "test", "title": "Codex capture"},
                "evidence": "codex tool output was denied",
            }
        )
    )
    assert (
        cli_diagnose.run(["diagnose", "capture", "--file", str(request_file), "--json"])
        == 0
    )
    captured = json.loads(capsys.readouterr().out)
    assert captured["ok"] is True
    assert captured["data"]["disposition"] == "created"

    output = StringIO()
    assert (
        cli_friction.run(
            ["friction", "list", "--json"],
            SimpleNamespace(stdout=output, stderr=StringIO()),
        )
        == 0
    )
    listed = json.loads(output.getvalue())
    assert listed["data"]["items"][0]["title"] == "Codex capture"
