from __future__ import annotations

import pytest
from varde_data.backends.sqlite import chat as chat_backend
from varde_data.backends.sqlite.chat import SqliteChat
from varde_data.config import DataConfig
from varde_data.errors import Invalid
from varde_data.open import open_data


def test_chat_connection_does_not_reassert_journal_mode(tmp_path, monkeypatch):
    statements = []
    connect = chat_backend.sqlite3.connect

    def connect_with_trace(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(chat_backend.sqlite3, "connect", connect_with_trace)
    repo = SqliteChat(tmp_path)
    initial = sum("journal_mode" in statement.lower() for statement in statements)
    statements.clear()

    repo.create_thread("instance:worker-1", agent_id="worker-1")
    repo.append_bot("instance:worker-1", "worker-1", 1, "update", "streaming")

    repeated = sum("journal_mode" in statement.lower() for statement in statements)
    assert initial == 1
    assert repeated == 0
    with connect(repo.path) as reopened:
        assert reopened.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_chat_domain_is_registered_and_creates_main_thread(tmp_path):
    chat = open_data(tmp_path, DataConfig()).chat
    assert chat.get_thread("main").kind == "main"
    assert [row.thread_key for row in chat.page("main")] == []


def test_thread_archive_bot_state_and_turn_records(tmp_path):
    repo = SqliteChat(tmp_path)
    repo.create_thread("instance:agent-1", agent_id="agent-1", label="Builder")
    row = repo.append_user("instance:agent-1", "user-1", "hello")

    archived = repo.archive_thread("instance:agent-1", "2026-10-25T11:00:00Z")
    assert archived.archived_at == "2026-10-25T11:00:00Z"
    assert [message.id for message in repo.page("instance:agent-1")] == [row.id]

    bot = repo.set_chat_bot("main", "manager", "started", 20, "running", 1)
    assert repo.get_chat_bot("main") == bot
    turn = repo.record_turn("main", "manager", 5, None)
    assert turn.last_event_seq is None


def test_projection_cursor_persists_and_legacy_backfill_replays_final_message(tmp_path):
    repo = SqliteChat(tmp_path)
    repo.create_thread("instance:agent-1", agent_id="agent-1")
    repo.append_bot("instance:agent-1", "agent-1", 10, "answer", "final")
    repo.save_processed_event_sequence("agent-1", 18)
    assert repo.processed_event_sequences() == {"agent-1": 18}

    # Simulate a pre-cursor database at schema v2. The legacy message points at
    # the first event of its turn, so migration backs up one sequence to replay it.
    with repo._connection() as db:
        db.execute("DROP TABLE chat_projection_cursors")
        db.execute("PRAGMA user_version = 2")

    migrated = SqliteChat(tmp_path)
    assert migrated.processed_event_sequences() == {"agent-1": 9}


def test_user_append_is_idempotent_and_thread_scoped(tmp_path):
    repo = SqliteChat(tmp_path)
    repo.create_thread("instance:agent-1", agent_id="agent-1", plan_id="plan-1")
    repo.create_thread("instance:agent-2", agent_id="agent-2", plan_id="plan-1")

    first = repo.append_user("instance:agent-1", "message-1", "hello")
    replay = repo.append_user("instance:agent-1", "message-1", "hello")
    other = repo.append_user("instance:agent-2", "message-2", "there")

    assert replay == first
    assert [row.id for row in repo.page("instance:agent-1")] == ["message-1"]
    assert [row.id for row in repo.page("instance:agent-2")] == ["message-2"]
    assert first.reply_to is None
    assert other.thread_key == "instance:agent-2"


def test_user_delivery_queue_survives_repository_reopen(tmp_path):
    repo = SqliteChat(tmp_path)
    first, inserted = repo.append_user_once("main", "message-1", "hello")

    assert inserted
    assert repo.pending_user_messages() == (first,)
    replay, inserted = repo.append_user_once("main", "message-1", "changed text")
    assert not inserted
    assert replay == first
    assert repo.mark_user_delivered("main", "message-1")
    assert not repo.mark_user_delivered("main", "message-1")

    reopened = SqliteChat(tmp_path)
    assert reopened.pending_user_messages() == ()
    assert reopened.append_user_once("main", "message-1", "hello") == (first, False)


def test_reply_to_must_be_a_message_in_the_same_thread(tmp_path):
    repo = SqliteChat(tmp_path)
    repo.create_thread("instance:agent-1", agent_id="agent-1")
    repo.create_thread("instance:agent-2", agent_id="agent-2")
    user = repo.append_user("instance:agent-1", "user-1", "question")
    event = repo.append_event("handoff", "handoff summary", None, "instance:agent-1")

    reply = repo.append_user("instance:agent-1", "reply-1", "answer", user.id)
    assert reply.reply_to == user.id
    for reply_to in (event.id, "missing"):
        with pytest.raises(Invalid):
            repo.append_user(
                "instance:agent-1", f"invalid-{reply_to}", "answer", reply_to
            )
    with pytest.raises(Invalid):
        repo.append_user("instance:agent-2", "cross-thread", "answer", user.id)


def test_message_changes_are_ordered_and_updates_get_a_new_change_seq(tmp_path):
    repo = SqliteChat(tmp_path)
    repo.create_thread("instance:agent-1", agent_id="agent-1")
    bot = repo.append_bot("instance:agent-1", "agent-1", 10, "hel", "streaming")
    updated = repo.update_bot_text("instance:agent-1", bot.id, "hello", "final")
    user = repo.append_user("instance:agent-1", "user-1", "hi", bot.id)

    assert updated.change_seq > bot.change_seq
    assert user.change_seq > updated.change_seq
    assert [
        row.id for row in repo.changes_after("instance:agent-1", bot.change_seq)
    ] == [
        bot.id,
        user.id,
    ]
    assert [
        row.id for row in repo.page("instance:agent-1", before=user.seq, limit=1)
    ] == [updated.id]


def test_takeover_queue_returns_each_ready_row_until_sent_once(tmp_path):
    repo = SqliteChat(tmp_path)
    repo.create_thread("instance:agent-1", agent_id="agent-1")
    assert repo.acquire("instance:agent-1", "browser-1", "2026-10-25T10:00:00Z")
    takeover = repo.get_takeover("instance:agent-1")
    assert takeover is not None
    assert takeover.holder_client == "browser-1"
    first = repo.enqueue(
        "instance:agent-1", "relay", "info", "first", "2026-10-25T10:01:00Z", "r1"
    )
    second = repo.enqueue(
        "instance:agent-1", "bot", "wake", "second", "2026-10-25T10:02:00Z"
    )

    assert repo.next_queued("instance:agent-1") is None
    assert repo.release("instance:agent-1", "browser-1", "2026-10-25T10:03:00Z")
    assert repo.next_queued("instance:agent-1") == first
    with pytest.raises(Invalid, match="only after SENT"):
        repo.mark_delivered(
            "instance:agent-1", first.id, "SKIPPED_BUSY", "2026-10-25T10:04:00Z"
        )
    assert repo.next_queued("instance:agent-1") == first
    assert repo.mark_delivered(
        "instance:agent-1", first.id, "SENT", "2026-10-25T10:04:00Z"
    )
    assert not repo.mark_delivered(
        "instance:agent-1", first.id, "SENT", "2026-10-25T10:05:00Z"
    )
    assert repo.next_queued("instance:agent-1") == second


def test_queue_enqueue_is_idempotent_by_request_id(tmp_path):
    repo = SqliteChat(tmp_path)
    repo.create_thread("instance:agent-1", agent_id="agent-1")
    first = repo.enqueue("instance:agent-1", "relay", "info", "x", "t1", "r1")
    replay = repo.enqueue("instance:agent-1", "relay", "info", "x", "t2", "r1")
    assert replay == first
