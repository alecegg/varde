from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fixtures.sessions.build_opencode import build as build_opencode
from varde_learn.loop.review.inventory import _activity, build_inventory, in_window
from varde_learn.loop.sources import Location

START = datetime(2026, 10, 23, tzinfo=UTC)
END = datetime(2026, 10, 24, tzinfo=UTC)


def _location(harness: str, root: Path) -> Location:
    return Location(harness, root, "config", "ok", "")


def _set_recent(path: Path) -> None:
    stamp = START.timestamp() + 60
    os.utime(path, (stamp, stamp))


def _jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    _set_recent(path)


def test_window_edges_are_inclusive() -> None:
    assert in_window(
        {"first_activity": START.isoformat(), "last_activity": START.isoformat()},
        (START, END),
    )
    assert in_window(
        {
            "first_activity": "2026-10-22T23:00:00+00:00",
            "last_activity": END.isoformat(),
        },
        (START, END),
    )


def test_real_claude_discovery_includes_subagent(tmp_path: Path) -> None:
    root = tmp_path / "claude-projects"
    project = root / "-sample"
    _jsonl(
        project / "parent.jsonl",
        [
            {"sessionId": "parent"},
            {"type": "user", "cwd": "/elsewhere", "timestamp": START.isoformat()},
        ],
    )
    _jsonl(
        project / "parent" / "subagents" / "agent-worker.jsonl",
        [
            {
                "type": "user",
                "isSidechain": True,
                "agentId": "worker",
                "timestamp": START.isoformat(),
            }
        ],
    )
    inventory = build_inventory([_location("claude", root)], (START, END))
    assert {row["kind"] for row in inventory.sessions} == {"session", "subagent"}
    assert all(row["status"] == "analyzable" for row in inventory.sessions)
    child = next(row for row in inventory.sessions if row["kind"] == "subagent")
    assert child["parent_id"] == "parent"
    assert child["project"] == "outside any repo"


def test_large_claude_session_and_codex_rollout_are_discovered(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    claude_root = tmp_path / "claude"
    claude_file = claude_root / "project" / "large.jsonl"
    claude_file.parent.mkdir(parents=True)
    claude_file.write_text(
        json.dumps({"sessionId": "large"})
        + "\n"
        + json.dumps(
            {"type": "user", "cwd": "/outside", "timestamp": START.isoformat()}
        )
        + "\n"
        + (json.dumps({"type": "assistant", "text": "x" * 1024}) + "\n") * 300
    )
    _set_recent(claude_file)
    claude = build_inventory([_location("claude", claude_root)], (START, END))
    assert claude.sessions[0]["session_id"] == "large"
    assert claude.sessions[0]["status"] == "analyzable"

    codex_root = tmp_path / "codex-large"
    rollout = codex_root / "sessions" / "rollout-large.jsonl"
    _jsonl(
        rollout,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "large-thread",
                    "cli_version": "0.162.1",
                    "cwd": "/outside",
                    "timestamp": START.isoformat(),
                },
            },
            {
                "type": "response_item",
                "timestamp": START.isoformat(),
                "payload": {"type": "message", "role": "user", "content": "request"},
            },
        ],
    )
    with rollout.open("ab") as stream:
        stream.write((json.dumps({"type": "ignored"}) + "\n").encode() * 1_100_000)
    _set_recent(rollout)
    codex = build_inventory([_location("codex", codex_root)], (START, END))
    assert any(row["session_id"] == "large-thread" for row in codex.sessions)


def test_real_codex_discovery_links_worker_rollout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    root = tmp_path / "codex"
    sessions = root / "sessions"

    def write_rollout(name: str, thread: str, parent: str | None) -> None:
        _jsonl(
            sessions / f"rollout-{name}.jsonl",
            [
                {
                    "type": "session_meta",
                    "payload": {
                        "id": thread,
                        "cli_version": "0.162.1",
                        "cwd": "/outside/repo",
                        "parent_thread_id": parent,
                        "timestamp": START.isoformat(),
                    },
                },
                {
                    "type": "response_item",
                    "timestamp": START.isoformat(),
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"text": "request"}],
                    },
                },
            ],
        )

    write_rollout("parent", "parent-thread", None)
    write_rollout("worker", "worker-thread", "parent-thread")
    inventory = build_inventory([_location("codex", root)], (START, END))
    worker = next(
        row for row in inventory.sessions if row["session_id"] == "worker-thread"
    )
    assert worker["kind"] == "subagent"
    assert worker["parent_id"] == "parent-thread"
    assert worker["status"] == "analyzable"


def test_real_opencode_discovery_uses_sqlite_activity(tmp_path: Path) -> None:
    root = tmp_path / "opencode"
    database = root / "opencode.db"
    build_opencode(database, tmp_path / "outside")
    activity_ms = int((START.timestamp() + 30) * 1000)
    with sqlite3.connect(database) as db:
        db.execute(
            "UPDATE session_v2 SET directory=?,time_updated=? WHERE id=?",
            ("/outside/repo", activity_ms, "opencode-session"),
        )
        db.execute(
            "UPDATE session_message SET time_created=?,time_updated=? "
            "WHERE session_id=?",
            (activity_ms, activity_ms, "opencode-session"),
        )
    inventory = build_inventory([_location("opencode", root)], (START, END))
    assert len(inventory.sessions) == 1
    row = inventory.sessions[0]
    assert row["path"].endswith("opencode.db#opencode-session")
    assert row["first_activity"].startswith("2026-10-23T00:00:30")
    assert row["status"] == "analyzable"


def test_real_pi_discovery_maps_sources_and_reports_version_skips(
    tmp_path: Path,
) -> None:
    root = tmp_path / "pi"
    session_dir = root / "--sample--"
    valid_a = session_dir / "2026-10-23T00-00-00-a.jsonl"
    valid_b = session_dir / "2026-10-23T00-01-00-b.jsonl"
    _jsonl(
        valid_a,
        [
            {
                "type": "session",
                "version": 3,
                "id": "pi-a",
                "timestamp": START.isoformat(),
                "cwd": "/outside/repo",
            },
            {"type": "message", "timestamp": START.isoformat()},
        ],
    )
    _jsonl(
        valid_b,
        [
            {
                "type": "session",
                "version": 3,
                "id": "pi-b",
                "timestamp": START.isoformat(),
                "cwd": "/outside/repo",
            },
            {"type": "message", "timestamp": START.isoformat()},
        ],
    )
    _jsonl(
        session_dir / "2026-10-23T00-02-00-old.jsonl",
        [{"type": "session", "version": 2, "cwd": "/outside/repo"}],
    )
    inventory = build_inventory([_location("pi", root)], (START, END))
    assert {row["session_id"] for row in inventory.sessions} == {"pi-a", "pi-b"}
    assert {Path(row["path"]) for row in inventory.sessions} == {valid_a, valid_b}
    assert all(row["status"] == "analyzable" for row in inventory.sessions)
    assert any(
        "unsupported versions" in status["reason"] for status in inventory.statuses
    )


def test_out_of_window_and_activity_unknown_remain_visible(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "claude"
    old = root / "project" / "old.jsonl"
    _jsonl(
        old,
        [
            {
                "sessionId": "old",
                "type": "user",
                "timestamp": "2026-10-22T12:00:00Z",
                "cwd": str(tmp_path / "outside"),
            }
        ],
    )
    old_stamp = START.timestamp() - 3600
    os.utime(old, (old_stamp, old_stamp))
    unreadable = root / "project" / "unknown.jsonl"
    _jsonl(
        unreadable,
        [{"sessionId": "unknown", "type": "user", "cwd": str(tmp_path / "outside")}],
    )
    _set_recent(unreadable)

    def unknown_activity(row, path, harness, window_start, opencode_times):
        if path.name == "unknown.jsonl":
            return None, None
        return _activity(row, path, harness, window_start, opencode_times)

    monkeypatch.setattr("varde_learn.loop.review.inventory._activity", unknown_activity)
    inventory = build_inventory([_location("claude", root)], (START, END))
    outcomes = {row["path"]: row["status"] for row in inventory.sessions}
    assert outcomes[str(old)] == "skipped: out of window"
    assert outcomes[str(unreadable)] == "skipped: activity unknown"


def test_discovery_failure_is_local_to_root(tmp_path: Path, monkeypatch) -> None:
    def fail(
        harness: str,
        root: Path,
        window_start=None,
        pending_paths=None,
        include_skipped=False,
    ):
        raise OSError("fixture root failed")

    monkeypatch.setattr("varde_learn.loop.review.inventory.discover_root", fail)
    inventory = build_inventory(
        [
            _location("claude", tmp_path / "broken"),
            Location("pi", tmp_path / "missing", "config", "missing", "absent"),
        ],
        (START, END),
    )
    assert inventory.statuses[0]["status"] == "error"
    assert "fixture root failed" in inventory.statuses[0]["reason"]
    assert inventory.statuses[1]["status"] == "missing"
