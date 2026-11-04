from uuid import uuid4

import pytest
from varde_runner.store import SessionStore


def test_store_wal_persists_sessions_and_append_only_events(tmp_path):
    store = SessionStore(tmp_path)
    before_session = store.change_count()
    store.create_session("s1", "paseo", {"id": "remote-1"}, "planner")
    after_session = store.change_count()
    assert after_session > before_session
    event = store.append_event("s1", "status", {"status": "running"})
    assert store.change_count() > after_session

    assert event == 1
    session = store.get_session("s1")
    assert session is not None
    assert session["role"] == "planner"
    assert session["last_event_seq"] == 1
    assert store.events_after("s1", 0)[0]["seq"] == 1
    assert store.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_commit_hook_errors_do_not_fail_committed_appends(tmp_path, caplog):
    store = SessionStore(tmp_path)
    store.create_session("s1", "paseo", {}, "planner")

    def broken_hook(session_id):
        raise RuntimeError(f"cannot wake {session_id}")

    store.on_commit = broken_hook

    assert store.append_event("s1", "status", {}) == 1
    assert store.events_after("s1", 0)[0]["kind"] == "status"
    assert "session store commit hook failed for s1" in caplog.text


def test_append_events_rejects_external_transaction(tmp_path):
    store = SessionStore(tmp_path)
    store.create_session("s1", "paseo", {}, "planner")
    notifications = []
    store.on_commit = notifications.append
    store.connection.execute("BEGIN")

    with pytest.raises(RuntimeError, match="cannot run inside an external transaction"):
        store.append_events("s1", [("status", {})])

    store.connection.rollback()
    assert store.events_after("s1", 0) == []
    assert notifications == []


def test_socket_is_private_and_sessions_can_be_reconciled(
    tmp_path, require_unix_socket
):
    from varde_runner.ipc import create_server_socket

    path = tmp_path.parents[2] / f"varde-{uuid4().hex[:8]}.sock"
    sock = create_server_socket(path)
    try:
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        sock.close()
        path.unlink(missing_ok=True)


def test_latest_schema_and_optional_session_fields(tmp_path):
    store = SessionStore(tmp_path)
    assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 7
    store.create_session(
        "s1",
        "codex",
        {"id": "remote-1"},
        "planner",
        harness="codex",
        agent_id="agent-1",
        lifecycle="running",
        capabilities={"interrupt": True},
    )
    session = store.get_session("s1")
    assert session is not None
    assert session["agent_id"] == "agent-1"
    assert session["lifecycle"] == "running"
    assert session["capabilities"] == '{"interrupt": true}'
    store.close()
    reopened = SessionStore(tmp_path)
    reopened_session = reopened.get_session("s1")
    assert reopened_session is not None
    assert reopened_session["agent_id"] == "agent-1"
    reopened.upsert_workspace("w1", repo_root="/repo", cwd="/repo/work")
    workspace = reopened.get_workspace("w1")
    assert workspace is not None
    assert workspace["cwd"] == "/repo/work"


def test_lifecycle_validation_and_decision_event_round_trip(tmp_path):
    store = SessionStore(tmp_path)
    store.create_session("s1", "paseo", {}, "planner")
    with pytest.raises(ValueError, match="invalid lifecycle"):
        store.update_session("s1", lifecycle="unknown")
    store.record_decision_event(
        "r1", card_kind="permission", request_key="path_scope:/tmp"
    )
    assert store.answer_decision_event("r1", "approve") is True
    assert store.answer_decision_event("r1", "deny") is False
    row = store.connection.execute(
        "SELECT * FROM decision_event WHERE request_id = 'r1'"
    ).fetchone()
    assert row["response"] == "approve"
    assert row["answered_at"] is not None


def test_status_updates_derive_lifecycle_but_preserve_archived(tmp_path):
    store = SessionStore(tmp_path)
    store.create_session("s1", "paseo", {}, "planner")
    store.update_session("s1", status="running")
    session = store.get_session("s1")
    assert session is not None and session["lifecycle"] == "running"
    store.update_session("s1", lifecycle="archived")
    store.update_session("s1", status="error")
    session = store.get_session("s1")
    assert session is not None and session["lifecycle"] == "archived"


def test_invalid_lifecycle_rejected_on_create(tmp_path):
    store = SessionStore(tmp_path)
    with pytest.raises(ValueError, match="invalid lifecycle"):
        store.create_session("bad", "paseo", {}, "planner", lifecycle="unknown")


def test_archived_lifecycle_is_terminal(tmp_path):
    store = SessionStore(tmp_path)
    store.create_session("s1", "paseo", {}, "planner", lifecycle="archived")
    with pytest.raises(ValueError, match="archived lifecycle is terminal"):
        store.update_session("s1", lifecycle="idle")


def test_workspace_upsert_preserves_optional_metadata(tmp_path):
    store = SessionStore(tmp_path)
    store.upsert_workspace(
        "w1",
        repo_root="/repo",
        cwd="/repo/work",
        worktree="/tree",
        branch="feature",
        archived_at="2026-10-21T00:00:00+00:00",
    )
    store.upsert_workspace("w1", repo_root="/repo", cwd="/repo/work")
    workspace = store.get_workspace("w1")
    assert workspace is not None
    assert workspace["worktree"] == "/tree"
    assert workspace["branch"] == "feature"
    assert workspace["archived_at"] == "2026-10-21T00:00:00+00:00"


def test_decision_event_validates_fields_and_answers_pending_only(tmp_path):
    store = SessionStore(tmp_path)
    with pytest.raises(ValueError, match="invalid decision event fields"):
        store.record_decision_event("bad", command="secret-shaped")
    with pytest.raises(ValueError, match="invalid decision response"):
        store.record_decision_event("bad-response", response="maybe")
    assert store.answer_decision_event("missing", "approve") is False
    store.record_decision_event("pending", card_kind="permission")
    assert store.answer_decision_event("pending", "approve") is True
    assert store.answer_decision_event("pending", "deny") is False
    columns = {
        row["name"]
        for row in store.connection.execute("PRAGMA table_info(decision_event)")
    }
    assert not columns.intersection(
        {"command", "full_command", "secret", "credentials"}
    )


def test_guard_verdicts_are_idempotent_and_page_by_id(tmp_path):
    store = SessionStore(tmp_path)
    assert store.record_guard_verdict(
        "s1",
        "r1",
        "cmd:git",
        "command",
        "GITHUB_TOKEN=prompt-secret",
        "approve",
        "reason password=hunter2",
        False,
    )
    assert not store.record_guard_verdict(
        "s1", "r1", "other", "command", "changed", "escalate", "duplicate", True
    )
    store.record_guard_verdict(
        "s2", "r2", "cmd:git", "command", "p2", "escalate", "unknown", True
    )
    page = store.guard_verdicts(1)
    assert page[0]["request_id"] == "r2"
    assert store.guard_verdicts(1, before_id=page[0]["id"])[0]["request_id"] == "r1"
    saved = store.guard_verdict_for("s1", "r1")
    assert saved is not None
    assert saved["reason"] == "reason [redacted]"
    assert saved["prompt"] == "[redacted]"
    assert len(store.guard_verdicts(0)) == 1


def test_guard_verdict_page_limit_is_capped_at_500(tmp_path):
    store = SessionStore(tmp_path)
    store.connection.executemany(
        "INSERT INTO guard_verdicts "
        "(ts, session_id, request_id, request_key, request_kind, prompt, verdict, "
        "reason, escalated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "2026-01-01",
                "s1",
                f"r{index}",
                "key",
                "kind",
                "p",
                "escalate",
                "r",
                1,
            )
            for index in range(501)
        ],
    )
    store.connection.commit()
    assert len(store.guard_verdicts(501)) == 500


def test_record_guard_verdict_rejects_noncanonical_verdict(tmp_path):
    store = SessionStore(tmp_path)
    with pytest.raises(ValueError, match="invalid guard verdict"):
        store.record_guard_verdict(
            "s1", "r1", "key", "kind", "p", "approved", "r", False
        )


def test_approvals_by_pattern_uses_store_revocations(tmp_path):
    from varde_runner.guard_log import approvals_by_pattern

    store = SessionStore(tmp_path)
    store.record_guard_verdict(
        "s1", "r1", "cmd:git", "command", "p", "approve", "ok", False
    )
    store.record_guard_verdict(
        "s2", "r2", "cmd:git", "command", "p", "escalate", "unknown", True
    )
    store.revoke_guard_pattern("cmd:git")
    first = store.guard_verdict_for("s1", "r1")
    assert first is not None
    assert approvals_by_pattern(
        store.guard_verdicts(20), store.revoked_guard_patterns()
    ) == [
        {
            "request_key": "cmd:git",
            "count": 1,
            "last_ts": first["ts"],
            "revoked": True,
        }
    ]


def test_guard_pattern_revocation_round_trip(tmp_path):
    store = SessionStore(tmp_path)
    store.revoke_guard_pattern("cmd:git")
    assert store.revoked_guard_patterns() == frozenset({"cmd:git"})
    store.unrevoke_guard_pattern("cmd:git")
    assert store.revoked_guard_patterns() == frozenset()


def test_existing_store_without_guard_tables_migrates(tmp_path):
    store = SessionStore(tmp_path)
    store.connection.execute("DROP TABLE guard_verdicts")
    store.connection.execute("DROP TABLE guard_revocations")
    store.connection.execute("PRAGMA user_version = 4")
    store.connection.commit()
    store.close()
    migrated = SessionStore(tmp_path)
    names = {
        row[0]
        for row in migrated.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"guard_verdicts", "guard_revocations"} <= names
    assert migrated.connection.execute("PRAGMA user_version").fetchone()[0] == 7
