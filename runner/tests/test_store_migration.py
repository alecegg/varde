import sqlite3

import pytest
from varde_runner.store import SessionStore


def _guard_tables(store):
    rows = store.connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'guard_%'"
    ).fetchall()
    return {row[0] for row in rows}


def test_legacy_store_migrates_in_place_and_keeps_reads(tmp_path):
    path = tmp_path / "runner.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """CREATE TABLE sessions (
        id TEXT PRIMARY KEY, backend TEXT NOT NULL, ref TEXT NOT NULL,
        role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unknown',
        idle_status TEXT NOT NULL DEFAULT 'unknown',
        last_event_seq INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
        kind TEXT NOT NULL, payload TEXT NOT NULL);
        INSERT INTO sessions(id, backend, ref, role, status)
        VALUES ('old', 'paseo', '{}', 'planner', 'running');
        INSERT INTO sessions(id, backend, ref, role, status)
        VALUES ('error', 'codex', '{}', 'builder', 'error');
        INSERT INTO sessions(id, backend, ref, role, status)
        VALUES ('unknown', 'pi', '{}', 'reviewer', 'unknown');
        INSERT INTO events(session_id, kind, payload)
        VALUES ('old', 'status', '{"status":"running"}');"""
    )
    connection.close()

    store = SessionStore(tmp_path)
    session = store.get_session("old")
    assert session is not None
    assert session["status"] == "running"
    assert session["agent_id"] == "old"
    assert session["harness"] == "paseo"
    assert session["lifecycle"] == "running"
    assert store.events_after("old", 0)[0]["payload"] == {"status": "running"}
    error_session = store.get_session("error")
    unknown_session = store.get_session("unknown")
    assert error_session is not None and error_session["lifecycle"] == "failed"
    assert unknown_session is not None and unknown_session["lifecycle"] == "idle"
    assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 7
    assert _guard_tables(store) == {"guard_revocations", "guard_verdicts"}
    before_session = store.get_session("old")
    before_events = store.events_after("old", 0)
    store.close()

    reopened = SessionStore(tmp_path)
    assert reopened.get_session("old") == before_session
    assert reopened.events_after("old", 0) == before_events
    assert reopened.connection.execute("SELECT COUNT(*) FROM waits").fetchone()[0] == 0


def test_failed_migration_rolls_back_schema_changes(tmp_path):
    path = tmp_path / "runner.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, backend TEXT NOT NULL, "
        "ref TEXT NOT NULL, role TEXT NOT NULL)"
    )
    connection.execute("PRAGMA user_version = 1")
    connection.close()

    with pytest.raises(sqlite3.OperationalError):
        SessionStore(tmp_path)

    check = sqlite3.connect(path)
    names = {row[1] for row in check.execute("PRAGMA table_info(sessions)")}
    assert "agent_id" not in names
    assert check.execute("PRAGMA user_version").fetchone()[0] == 1
    check.close()


def test_schema_version_above_supported_version_is_rejected(tmp_path):
    path = tmp_path / "runner.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version = 8")
    connection.close()

    with pytest.raises(RuntimeError, match="unsupported store schema version: 8"):
        SessionStore(tmp_path)


def test_v2_store_migrates_to_v3_without_rewriting_events(tmp_path):
    path = tmp_path / "runner.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """CREATE TABLE sessions (
        id TEXT PRIMARY KEY, backend TEXT NOT NULL, ref TEXT NOT NULL,
        role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unknown',
        idle_status TEXT NOT NULL DEFAULT 'unknown',
        last_event_seq INTEGER NOT NULL DEFAULT 0,
        harness TEXT, agent_id TEXT, workspace_id TEXT, model TEXT,
        reasoning_effort TEXT, mode TEXT, lifecycle TEXT NOT NULL DEFAULT 'idle',
        capabilities TEXT NOT NULL DEFAULT '{}', created_at TEXT, updated_at TEXT);
        CREATE TABLE events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
        kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT);
        INSERT INTO sessions(id, backend, ref, role, last_event_seq)
        VALUES ('s1', 'paseo', '{}', 'planner', 2);
        INSERT INTO events(seq, session_id, kind, payload, created_at)
        VALUES (1, 's1', 'tool', '{"call_id":"legacy"}', 'old-time');
        PRAGMA user_version = 2;"""
    )
    connection.close()

    store = SessionStore(tmp_path)
    assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 7
    assert _guard_tables(store) == {"guard_revocations", "guard_verdicts"}
    session = store.get_session("s1")
    assert session is not None
    assert session["no_progress_restarts"] == 0
    assert session["seq_at_last_start"] == 0
    event = store.events_after("s1", 0)[0]
    assert event == {
        "seq": 1,
        "session_id": "s1",
        "kind": "tool",
        "payload": {"call_id": "legacy"},
        "created_at": "old-time",
    }
    store.update_session("s1", no_progress_restarts=2, seq_at_last_start=1)
    session = store.get_session("s1")
    assert session is not None
    assert session["no_progress_restarts"] == 2


def test_v3_store_migrates_to_v4_and_preserves_existing_rows(tmp_path):
    path = tmp_path / "runner.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """CREATE TABLE sessions (
        id TEXT PRIMARY KEY, backend TEXT NOT NULL, ref TEXT NOT NULL,
        role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unknown',
        idle_status TEXT NOT NULL DEFAULT 'unknown',
        last_event_seq INTEGER NOT NULL DEFAULT 1,
        no_progress_restarts INTEGER NOT NULL DEFAULT 0,
        seq_at_last_start INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
        kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT);
        INSERT INTO sessions(id, backend, ref, role)
        VALUES ('s1', 'fake', '{}', 'builder');
        INSERT INTO events(session_id, kind, payload) VALUES ('s1', 'status', '{}');
        PRAGMA user_version = 3;"""
    )
    connection.close()

    store = SessionStore(tmp_path)
    assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 7
    assert _guard_tables(store) == {"guard_revocations", "guard_verdicts"}
    assert store.get_session("s1") is not None
    assert len(store.events_after("s1", 0)) == 1
    assert store.connection.execute("SELECT COUNT(*) FROM waits").fetchone()[0] == 0


def test_v5_store_gains_nullable_parent_id(tmp_path) -> None:
    path = tmp_path / "runner.sqlite3"
    first = SessionStore(path)
    first.create_session("s1", "b", {"provider": "b", "session_id": "r"}, "builder")
    first.connection.execute("ALTER TABLE sessions DROP COLUMN parent_id")
    first.connection.execute("PRAGMA user_version = 5")
    first.connection.commit()
    first.connection.close()

    store = SessionStore(path)

    assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 7
    before = store.get_session("s1")
    assert before is not None and before["parent_id"] is None
    store.update_session("s1", parent_id="p1")
    after = store.get_session("s1")
    assert after is not None and after["parent_id"] == "p1"


def test_v6_store_gains_nullable_launched_by(tmp_path) -> None:
    path = tmp_path / "runner.sqlite3"
    first = SessionStore(path)
    first.create_session("s1", "b", {"provider": "b", "session_id": "r"}, "builder")
    first.connection.execute("ALTER TABLE sessions DROP COLUMN launched_by")
    first.connection.execute("PRAGMA user_version = 6")
    first.connection.commit()
    first.connection.close()

    store = SessionStore(path)

    assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 7
    before = store.get_session("s1")
    assert before is not None and before["launched_by"] is None
    store.update_session("s1", launched_by="bot:manager")
    after = store.get_session("s1")
    assert after is not None and after["launched_by"] == "bot:manager"
