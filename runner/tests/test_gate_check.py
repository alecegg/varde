from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime

import pytest
import varde_runner
from varde_runner import gate_cli
from varde_runner.gate_check import check_gate
from varde_runner.gate_cli import main

RESTART = datetime(2026, 10, 25, 12, tzinfo=UTC)


def test_gate_passes_only_without_paseo_and_with_restart_recovery():
    sessions = [
        {
            "id": "native-1",
            "backend": "codex-app-server",
            "ref": json.dumps({"provider": "codex-app-server"}),
            "status": "running",
            "created_at": "2026-10-25T10:00:00Z",
        },
        {
            "id": "native-2",
            "backend": "claude-sdk",
            "ref": json.dumps({"provider": "claude-sdk"}),
            "status": "running",
            "created_at": "2026-10-25T11:00:00Z",
        },
    ]
    events = [
        {
            "session_id": "native-1",
            "kind": "resume",
            "created_at": "2026-10-25T12:01:00Z",
        },
        {
            "session_id": "native-2",
            "kind": "resume",
            "created_at": "2026-10-25T12:02:00Z",
        },
    ]

    result = check_gate(sessions, events, [], RESTART)

    assert result == {
        "paseo_sessions": 0,
        "paseo_bindings": 0,
        "running_at_restart": 2,
        "resumed_after_restart": 2,
        "running_resumed_after_restart": 2,
        "parked_after_restart": 0,
        "verdict_inputs_ok": True,
    }


def test_gate_fails_paseo_rows_missing_resume_and_parked_sessions():
    sessions = [
        {
            "id": "paseo-1",
            "backend": "claude",
            "ref": json.dumps({"provider": "paseo"}),
            "status": "running",
            "created_at": "2026-10-25T10:00:00Z",
        },
        {
            "id": "native-1",
            "backend": "codex-app-server",
            "ref": json.dumps({"provider": "codex-app-server"}),
            "status": "running",
            "created_at": "2026-10-25T10:00:00Z",
        },
        {
            "id": "native-2",
            "backend": "claude-sdk",
            "ref": json.dumps({"provider": "claude-sdk"}),
            "status": "running",
            "created_at": "2026-10-25T10:00:00Z",
        },
    ]
    events = [
        {
            "session_id": "native-1",
            "kind": "resume",
            "created_at": "2026-10-25T12:01:00Z",
        },
        {
            "session_id": "native-2",
            "kind": "parked",
            "created_at": "2026-10-25T12:02:00Z",
        },
    ]
    bindings = [{"session_id": "paseo-1"}]

    result = check_gate(sessions, events, bindings, RESTART)

    assert result["paseo_sessions"] == 1
    assert result["paseo_bindings"] == 1
    assert result["running_at_restart"] == 3
    assert result["resumed_after_restart"] == 1
    assert result["parked_after_restart"] == 1
    assert result["verdict_inputs_ok"] is False


def test_gate_does_not_substitute_unrelated_resume_for_running_session():
    sessions = [
        {
            "id": session_id,
            "backend": "native",
            "ref": "{}",
            "status": "running" if session_id != "c" else "created",
            "created_at": "2026-10-25T10:00:00Z",
        }
        for session_id in ("a", "b", "c")
    ]
    events = [
        {
            "session_id": session_id,
            "kind": "resume",
            "created_at": f"2026-10-25T12:0{index}:00Z",
        }
        for index, session_id in enumerate(("a", "c"), start=1)
    ]

    result = check_gate(sessions, events, [], RESTART)

    assert result["running_at_restart"] == 2
    assert result["resumed_after_restart"] == 2
    assert result["running_resumed_after_restart"] == 1
    assert result["verdict_inputs_ok"] is False


def test_gate_bounds_restart_events_by_since_and_until():
    event = {
        "session_id": "native-1",
        "kind": "resume",
        "created_at": "2026-10-25T12:01:00Z",
    }
    session = {
        "id": "native-1",
        "backend": "native",
        "ref": "{}",
        "status": "running",
        "created_at": "2026-10-25T10:00:00Z",
    }

    result = check_gate(
        [session],
        [event],
        [],
        RESTART,
        since=datetime(2026, 10, 25, 12, 1, 1, tzinfo=UTC),
        until=datetime(2026, 10, 25, 12, 2, tzinfo=UTC),
    )

    assert result["resumed_after_restart"] == 0
    assert result["verdict_inputs_ok"] is False


def test_gate_cli_reads_runner_store_and_emits_json(tmp_path, monkeypatch, capsys):
    database = tmp_path / ".cache" / "dashboard" / "runner.sqlite3"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as db:
        db.executescript(
            """
            CREATE TABLE sessions (
                id TEXT, backend TEXT, ref TEXT, status TEXT, created_at TEXT
            );
            CREATE TABLE events (
                session_id TEXT, kind TEXT, created_at TEXT
            );
            CREATE TABLE session_address_bindings (session_id TEXT);
            INSERT INTO sessions VALUES
                ('a1', 'native', '{"provider":"native"}', 'running',
                 '2026-10-25T10:00:00Z');
            INSERT INTO events VALUES
                ('a1', 'resume', '2026-10-25T12:01:00Z');
            """
        )
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))

    status = main(["check", "--restart-at", "2026-10-25T12:00:00Z", "--json"])

    assert status == 0
    assert json.loads(capsys.readouterr().out)["verdict_inputs_ok"] is True


def test_runner_dispatches_gate_command(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "varde-runner",
            "gate",
            "check",
            "--restart-at",
            "2026-10-25T12:00:00Z",
            "--json",
        ],
    )
    monkeypatch.setattr(gate_cli, "main", lambda argv: 7 if argv[0] == "check" else 8)

    with pytest.raises(SystemExit, match="7"):
        varde_runner.main()
