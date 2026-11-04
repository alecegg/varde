import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fixtures.sessions.build_opencode import build as build_opencode
from varde_learn.loop.diagnose.claude import ClaudeHarness
from varde_learn.loop.diagnose.list import discover_root
from varde_learn.loop.diagnose.opencode import OPENCODE_VERSION


def test_claude_root_discovery_includes_outside_repo_session_and_subagent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "projects"
    project = root / "-outside"
    project.mkdir(parents=True)
    session = project / "session.jsonl"
    session.write_text(
        json.dumps({"sessionId": "session"})
        + "\n"
        + json.dumps({"type": "user", "cwd": "/elsewhere", "timestamp": "now"})
        + "\n"
    )
    child_dir = project / "session" / "subagents"
    child_dir.mkdir(parents=True)
    (child_dir / "agent-worker.jsonl").write_text(
        json.dumps(
            {
                "parentUuid": None,
                "isSidechain": True,
                "agentId": "agent-worker",
                "type": "user",
                "message": {"role": "user", "content": "worker task"},
            }
        )
        + "\n"
    )
    (project / "broken.jsonl").write_text("not-json\n")

    discovery = discover_root("claude", root)
    rows, warnings = discovery.sessions, discovery.warnings

    assert any(
        "broken.jsonl" in warning and "malformed JSON" in warning
        for warning in warnings
    )
    assert [row.kind for row in rows] == ["session", "subagent"]
    assert rows[1].parent_id == "session"
    assert rows[1].session_id == "agent-worker"
    assert rows[1].parent_identity == "claude:-outside:session"
    assert rows[1].path.endswith("agent-worker.jsonl")
    assert rows[1].root == str(root)


def test_opencode_root_discovery_reports_version_mismatch(tmp_path: Path) -> None:
    database = tmp_path / "opencode" / "opencode.db"
    build_opencode(database, tmp_path)
    db = sqlite3.connect(database)
    db.execute(
        "INSERT INTO session_v2 "
        "(id,directory,version,time_created,time_updated) "
        "VALUES ('old','/outside','old-version',1,2)"
    )
    db.execute(
        "INSERT INTO session_v2 "
        "(id,directory,version,time_created,time_updated) "
        "VALUES ('current','/outside',?,1,3)",
        (OPENCODE_VERSION,),
    )
    db.execute(
        "INSERT INTO session_message "
        "(id,session_id,type,seq,time_created,time_updated,data) "
        "VALUES ('retro-msg','current','user',1,1,1,?)",
        (json.dumps({"text": "retro analyst review"}),),
    )
    db.commit()
    db.close()

    discovery = discover_root("opencode", tmp_path / "opencode")
    rows, warnings = discovery.sessions, discovery.warnings

    assert [row.session_id for row in rows] == ["opencode-session", "current"]
    assert any("old" in warning and "version" in warning for warning in warnings)
    assert rows[0].retro_analyst is False
    assert rows[1].retro_analyst is True
    assert rows[0].path.endswith("opencode.db#opencode-session")


def test_codex_root_discovery_keeps_outside_repo_worker_parent_link(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    sessions = tmp_path / "codex" / "sessions"
    sessions.mkdir(parents=True)

    def write_rollout(name: str, thread: str, parent: str | None) -> None:
        path = sessions / f"rollout-{name}.jsonl"
        header = {
            "type": "session_meta",
            "payload": {
                "id": thread,
                "cli_version": "0.162.1",
                "cwd": "/outside/repo",
                "parent_thread_id": parent,
            },
        }
        user = {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"text": "request"}],
            },
        }
        path.write_text(json.dumps(header) + "\n" + json.dumps(user) + "\n")

    write_rollout("parent", "parent-thread", None)
    write_rollout("worker", "worker-thread", "parent-thread")

    discovery = discover_root("codex", tmp_path / "codex")
    rows, warnings = discovery.sessions, discovery.warnings

    assert warnings == []
    worker = next(row for row in rows if row.session_id == "worker-thread")
    assert worker.cwd == "/outside/repo"
    assert worker.parent_identity == "codex:parent-thread"
    assert worker.root == str(tmp_path / "codex")
    assert worker.kind == "session"
    assert worker.parent_id == "parent-thread"


def test_repo_scoped_claude_discovery_still_filters_outside_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    projects = tmp_path / "projects"
    project = projects / "project"
    project.mkdir(parents=True)
    for session_id, cwd in (("inside", str(repo)), ("outside", "/outside")):
        (project / f"{session_id}.jsonl").write_text(
            json.dumps({"sessionId": session_id})
            + "\n"
            + json.dumps({"type": "user", "cwd": cwd})
            + "\n"
        )

    rows = ClaudeHarness().discover(repo=repo, roots={"claude": projects}, limit=10)

    assert [row["session_id"] for row in rows] == ["inside"]


def test_claude_root_discovery_reports_session_when_mtime_stat_fails(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "projects"
    project = root / "-outside"
    project.mkdir(parents=True)
    session = project / "session.jsonl"
    session.write_text(
        json.dumps({"sessionId": "session"})
        + "\n"
        + json.dumps({"type": "user", "cwd": "/elsewhere"})
        + "\n"
    )
    original_stat = Path.stat

    def stat_with_unreadable_mtime(path: Path, *args, **kwargs):
        if path == session:
            raise OSError("permission denied")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_with_unreadable_mtime)

    rows, warnings = ClaudeHarness().discover_root(root, window_start=datetime.now(UTC))

    assert warnings == []
    assert [row["session_id"] for row in rows] == ["session"]
