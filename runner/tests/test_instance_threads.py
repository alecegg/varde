from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.applications import Starlette
from varde_data.chat import open_chat
from varde_runner.chat_delivery import ChatDelivery
from varde_runner.instance_threads import InstanceThreads, _thread_label, plan_for_agent
from varde_runner.registry import SessionBinding, SessionRegistry
from varde_runner.supervisor import SendOutcome
from varde_runner.web.instance_threads_route import create_instance_threads_routes


class FakeStore:
    def __init__(
        self, sessions: list[dict[str, Any]], events: dict[str, list[dict[str, Any]]]
    ):
        self._sessions = sessions
        self._events = events
        self._change_count = 0
        self.sessions_calls = 0
        self.events_after_calls = 0
        self.event_cursors: list[tuple[str, int]] = []
        self.last_event_at_calls = 0

    def change_count(self):
        return self._change_count

    def sessions(self):
        self.sessions_calls += 1
        return self._sessions

    def get_session(self, session_id: str):
        return next((row for row in self._sessions if row["id"] == session_id), None)

    def events_after(self, session_id: str, seq: int):
        self.events_after_calls += 1
        self.event_cursors.append((session_id, seq))
        return [row for row in self._events.get(session_id, []) if row["seq"] > seq]

    def last_event_at(self, session_id: str):
        self.last_event_at_calls += 1
        return "2026-10-25T10:00:00Z" if self._events.get(session_id) else None


class FakeMessages:
    def __init__(self, records, note: str):
        self.records = records
        self.note = note

    def read_all(self):
        return SimpleNamespace(records=self.records)

    def read_note(self, _notes):
        return self.note


class FakeSupervisor:
    def __init__(self, data_dir, store):
        self.data_dir = data_dir
        self.store = store
        self.sent: list[tuple[str, str, str | None, bool]] = []

    def resolve_session(self, agent_id: str):
        return {"id": agent_id} if agent_id == "worker-1" else None

    def send(
        self,
        session_id: str,
        text: str,
        *,
        client_id: str | None = None,
        takeover_holder: bool = False,
    ):
        self.sent.append((session_id, text, client_id, takeover_holder))
        return asyncio.sleep(0, result=SendOutcome.SENT)


def _event(seq: int, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"seq": seq, "kind": kind, "payload": payload}


def _get(app: Starlette, path: str) -> tuple[int, dict[str, Any]]:
    async def dispatch():
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        raw_path, _, query = path.partition("?")
        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": raw_path,
                "raw_path": raw_path.encode(),
                "query_string": query.encode(),
                "root_path": "",
                "headers": [(b"host", b"localhost")],
                "client": ("127.0.0.1", 1),
                "server": ("localhost", 80),
            },
            receive,
            send,
        )
        start = next(row for row in messages if row["type"] == "http.response.start")
        body = b"".join(
            row.get("body", b"")
            for row in messages
            if row["type"] == "http.response.body"
        )
        return start["status"], body

    status, body = asyncio.run(dispatch())
    return status, json.loads(body)


def _session(
    *,
    agent_id: str = "worker-1",
    lifecycle: str = "idle",
    workspace_id: str = "worktree/2026-10-25-chat-threads-t5",
    parent_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": agent_id,
        "agent_id": agent_id,
        "role": "builder",
        "workspace_id": workspace_id,
        "parent_id": parent_id,
        "lifecycle": lifecycle,
    }


def test_plan_for_agent_matches_real_worktree_and_plain_workspace_names(tmp_path):
    plan_id = "2026-10-25-chat-threads"
    binding = SessionBinding(
        "plan-address", "fake", "fake", "orchestrator", "orchestrator", plan_id
    )
    sessions = [_session(agent_id="orchestrator"), _session(parent_id="orchestrator")]
    bindings = {"orchestrator": binding}

    plain_workspace = {**sessions[1], "workspace_id": "plain workspace"}
    assert plan_for_agent(plain_workspace, bindings, sessions, [plan_id]) == plan_id
    assert (
        plan_for_agent(
            {**sessions[1], "parent_id": None, "workspace_id": plan_id},
            {},
            [],
            [plan_id],
        )
        == plan_id
    )
    assert (
        plan_for_agent(
            {**sessions[1], "workspace_id": "worktree/2026-10-25-unrelated-task"},
            {},
            [],
            [plan_id],
        )
        is None
    )


def test_session_projection_is_idempotent_across_restart_and_archives(tmp_path):
    chat = open_chat(tmp_path)
    session = _session()
    events = {
        "worker-1": [
            _event(1, "text_delta", {"text": "Hello"}),
            _event(2, "text", {"text": "Hello from the worker"}),
            _event(
                3,
                "wait_created",
                {"request_id": "q-1", "question": [{"question": "Which?"}]},
            ),
            _event(
                4, "permission_requested", {"request_id": "q-1", "summary": "Which?"}
            ),
            _event(5, "wait_resolved", {"request_id": "q-1", "decision": "A"}),
            _event(
                6,
                "tool_intent",
                {"tool": "shell", "phase": "running", "input": "secret"},
            ),
            _event(7, "session_end", {"status": "completed"}),
            _event(8, "text_delta", {"text": "Partial turn"}),
            _event(9, "session_end", {"status": "completed"}),
        ]
    }
    store = FakeStore([session], events)
    supervisor = FakeSupervisor(tmp_path / "sessions", store)
    registry = SessionRegistry(supervisor.data_dir / "registry.json")
    registry.register(
        SessionBinding("worker-address", "fake", "fake", "worker-1", "builder")
    )
    handoff = SimpleNamespace(
        kind="info", text="handoff", from_="worker-address", notes="handoff.md"
    )
    messages = FakeMessages(
        [handoff], "Summary: continue the tests\nContext: private detail"
    )
    first = InstanceThreads(chat, ["2026-10-25-chat-threads"], messages=messages)

    asyncio.run(first.refresh(supervisor))
    before = chat.page("instance:worker-1", limit=50)
    bot_rows = [row for row in before if row.role == "bot"]
    assert [row.text for row in bot_rows] == ["Hello from the worker", "Partial turn"]
    assert all(row.state == "final" for row in bot_rows)
    assert sum(row.kind == "question" for row in before) == 1
    question = next(row for row in before if row.kind == "question")
    assert question.link is not None and "q-1" in question.link
    assert any(row.text == "Answered: A" for row in before)
    handoff_row = next(row for row in before if row.kind == "handoff")
    assert handoff_row.text == "Summary: continue the tests"
    assert handoff_row.link == "handoff.md"
    assert not any(
        "private detail" in row.text or "secret" in row.text for row in before
    )

    restarted = InstanceThreads(chat, ["2026-10-25-chat-threads"], messages=messages)
    rows = asyncio.run(restarted.refresh(supervisor))
    assert store.event_cursors[-1] == ("worker-1", 9)
    after = chat.page("instance:worker-1", limit=50)
    assert after == before
    assert rows[0]["plan_id"] == "2026-10-25-chat-threads"
    assert rows[0]["label"] == "Builder"

    store._sessions[0]["lifecycle"] = "archived"
    store._change_count += 1
    archived = asyncio.run(restarted.refresh(supervisor))[0]
    assert archived["state"] == "archived"
    assert chat.get_thread("instance:worker-1").archived_at is not None
    assert chat.page("instance:worker-1", limit=50) == before


def test_restart_does_not_duplicate_completed_multievent_bot_message(tmp_path):
    chat = open_chat(tmp_path)
    store = FakeStore(
        [_session()],
        {
            "worker-1": [
                _event(1, "text_delta", {"text": "Hello"}),
                _event(4, "text", {"text": "Hello world"}),
                _event(7, "status", {"status": "idle"}),
            ]
        },
    )
    supervisor = FakeSupervisor(tmp_path / "sessions", store)

    asyncio.run(InstanceThreads(chat).refresh(supervisor))
    first = [
        row for row in chat.page("instance:worker-1", limit=50) if row.role == "bot"
    ]
    assert [(row.source_event_seq, row.text, row.state) for row in first] == [
        (1, "Hello world", "final")
    ]
    assert chat.processed_event_sequences() == {"worker-1": 7}

    asyncio.run(InstanceThreads(chat).refresh(supervisor))
    after_restart = [
        row for row in chat.page("instance:worker-1", limit=50) if row.role == "bot"
    ]
    assert [(row.source_event_seq, row.text, row.state) for row in after_restart] == [
        (1, "Hello world", "final")
    ]


def test_projection_write_before_cursor_checkpoint_is_replayed_idempotently(
    tmp_path, monkeypatch
):
    chat = open_chat(tmp_path)
    store = FakeStore(
        [_session()],
        {
            "worker-1": [
                _event(1, "text_delta", {"text": "Hello"}),
                _event(4, "text", {"text": "Hello world"}),
            ]
        },
    )
    supervisor = FakeSupervisor(tmp_path / "sessions", store)
    save_cursor = chat.save_processed_event_sequence

    def fail_checkpoint(_agent_id: str, _sequence: int) -> None:
        raise OSError("simulated crash before cursor checkpoint")

    monkeypatch.setattr(chat, "save_processed_event_sequence", fail_checkpoint)
    with pytest.raises(OSError, match="cursor checkpoint"):
        asyncio.run(InstanceThreads(chat).refresh(supervisor))
    monkeypatch.setattr(chat, "save_processed_event_sequence", save_cursor)

    asyncio.run(InstanceThreads(chat).refresh(supervisor))
    rows = [
        row for row in chat.page("instance:worker-1", limit=50) if row.role == "bot"
    ]
    assert [(row.source_event_seq, row.text, row.state) for row in rows] == [
        (1, "Hello world", "final")
    ]
    assert chat.processed_event_sequences() == {"worker-1": 4}


def test_unchanged_refresh_skips_sqlite_and_session_reads(tmp_path, monkeypatch):
    chat = open_chat(tmp_path)
    store = FakeStore([_session(lifecycle="archived")], {"worker-1": []})
    supervisor = FakeSupervisor(tmp_path / "sessions", store)
    threads = InstanceThreads(chat)

    first = asyncio.run(threads.refresh(supervisor))
    assert first[0]["state"] == "archived"
    store_calls = (
        store.sessions_calls,
        store.events_after_calls,
        store.last_event_at_calls,
    )
    connections: list[object] = []
    writes: list[str] = []
    connect = sqlite3.connect

    def trace(statement: str) -> None:
        if (
            statement.lstrip()
            .upper()
            .startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
        ):
            writes.append(statement)

    def count_connections(*args, **kwargs):
        connections.append(args[0] if args else kwargs.get("database"))
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr(sqlite3, "connect", count_connections)
    second = asyncio.run(threads.refresh(supervisor))

    assert second == first
    assert connections == []
    assert writes == []
    assert (
        store.sessions_calls,
        store.events_after_calls,
        store.last_event_at_calls,
    ) == store_calls

    store._events["worker-1"].append(_event(1, "text", {"text": "New event"}))
    store._change_count += 1
    asyncio.run(threads.refresh(supervisor))
    assert connections
    assert writes
    assert store.events_after_calls == store_calls[1] + 1
    assert threads._event_sequences["worker-1"] == 1
    assert any(
        row.text == "New event" and row.source_event_seq == 1
        for row in chat.page("instance:worker-1", limit=50)
    )


def test_instance_user_reply_stays_routed_to_the_thread_owner(tmp_path):
    async def exercise():
        chat = open_chat(tmp_path)
        chat.create_thread("instance:worker-1", agent_id="worker-1", label="worker")
        target = chat.append_bot("instance:worker-1", "worker-1", 1, "question")
        message, _ = chat.append_user_once(
            "instance:worker-1", "user-1", "answer", reply_to=target.id
        )
        supervisor = FakeSupervisor(tmp_path / "sessions", FakeStore([], {}))

        async def get_supervisor():
            return supervisor

        delivery = ChatDelivery(chat, get_supervisor)
        assert await delivery._send("instance:worker-1", message)
        assert supervisor.sent == [("worker-1", "answer", "system:dashboard", True)]
        assert message.reply_to == target.id

    asyncio.run(exercise())


def test_instance_thread_api_filters_and_creates_legacy_threads(tmp_path):
    chat = open_chat(tmp_path)
    store = FakeStore([_session()], {"worker-1": []})
    supervisor = FakeSupervisor(tmp_path / "sessions", store)
    app = Starlette(
        routes=create_instance_threads_routes(
            InstanceThreads(chat, ["2026-10-25-chat-threads"]), lambda: supervisor
        )
    )

    status, response = _get(app, "/api/instance-threads?plan=2026-10-25-chat-threads")
    assert status == 200
    assert len(response["threads"]) == 1
    assert response["threads"][0]["agent_id"] == "worker-1"
    assert chat.get_thread("instance:worker-1").label is not None
    assert _get(app, "/api/instance-threads?agent=unknown")[0] == 404
    assert _get(app, "/api/instance-threads?plan=x&agent=worker-1")[0] == 400


def test_role_name_without_runner_session_has_no_instance_thread(tmp_path):
    chat = open_chat(tmp_path)
    supervisor = FakeSupervisor(tmp_path / "sessions", FakeStore([], {}))
    app = Starlette(
        routes=create_instance_threads_routes(InstanceThreads(chat), lambda: supervisor)
    )

    status, response = _get(app, "/api/instance-threads")
    assert status == 200
    assert response == {"threads": []}
    assert _get(app, "/api/instance-threads?agent=varde-builder")[0] == 404


def test_instance_thread_labels_use_role_and_plan_instead_of_agent_ids():
    assert _thread_label("51c8587d633a4a258a25b5de", "reviewer", None) == "Reviewer"
    assert (
        _thread_label("agent-guid", "orchestrator", "plan-123")
        == "Orchestrator plan-123"
    )


def test_projection_backfills_guid_label_on_existing_thread(tmp_path):
    chat = open_chat(tmp_path)
    chat.create_thread(
        "instance:51c8587d633a4a258a25b5de",
        agent_id="51c8587d633a4a258a25b5de",
        label="Builder (51c8)",
    )
    session = _session(agent_id="51c8587d633a4a258a25b5de", workspace_id="")
    supervisor = FakeSupervisor(tmp_path / "sessions", FakeStore([session], {}))

    asyncio.run(InstanceThreads(chat).refresh(supervisor))

    assert chat.get_thread("instance:51c8587d633a4a258a25b5de").label == "Builder"


def _bot_rows(chat, agent_id: str = "worker-1"):
    return [
        (row.source_event_seq, row.text, row.state)
        for row in chat.page(f"instance:{agent_id}", limit=50)
        if row.role == "bot"
    ]


def test_restart_between_text_delta_and_final_text_continues_one_row(tmp_path):
    chat = open_chat(tmp_path)
    events = {"worker-1": [_event(3, "text_delta", {"text": "Hel"})]}
    supervisor = FakeSupervisor(tmp_path / "sessions", FakeStore([_session()], events))

    asyncio.run(InstanceThreads(chat).refresh(supervisor))
    assert _bot_rows(chat) == [(3, "Hel", "streaming")]
    assert chat.processed_event_sequences() == {"worker-1": 2}

    events["worker-1"] += [
        _event(5, "text_delta", {"text": "lo"}),
        _event(9, "text", {"text": "Hello"}),
    ]
    supervisor.store._change_count += 1
    asyncio.run(InstanceThreads(chat).refresh(supervisor))
    assert _bot_rows(chat) == [(3, "Hello", "final")]
    assert chat.processed_event_sequences() == {"worker-1": 9}


def test_restart_mid_stream_resumes_accumulator_across_gaps_and_archive(tmp_path):
    chat = open_chat(tmp_path)
    events = {
        "worker-1": [
            _event(1, "text", {"text": "first"}),
            _event(4, "text_delta", {"text": "sec"}),
            _event(6, "text_delta", {"text": "ond"}),
        ]
    }
    session = _session()
    supervisor = FakeSupervisor(tmp_path / "sessions", FakeStore([session], events))
    asyncio.run(InstanceThreads(chat).refresh(supervisor))
    assert chat.processed_event_sequences() == {"worker-1": 3}

    session["lifecycle"] = "archived"
    events["worker-1"].append(_event(12, "session_end", {}))
    supervisor.store._change_count += 1
    asyncio.run(InstanceThreads(chat).refresh(supervisor))
    assert _bot_rows(chat) == [(1, "first", "final"), (4, "second", "final")]


def test_crash_between_event_write_and_projection_is_projected_on_restart(tmp_path):
    chat = open_chat(tmp_path)
    events = {"worker-1": [_event(1, "text", {"text": "done"})]}
    supervisor = FakeSupervisor(tmp_path / "sessions", FakeStore([_session()], events))
    asyncio.run(InstanceThreads(chat).refresh(supervisor))

    events["worker-1"].append(_event(2, "text_delta", {"text": "new"}))
    asyncio.run(InstanceThreads(chat).refresh(supervisor))
    assert _bot_rows(chat) == [(1, "done", "final"), (2, "new", "streaming")]


def test_legacy_streaming_row_without_cursor_replays_only_its_tail(tmp_path):
    chat = open_chat(tmp_path)
    chat.create_thread("instance:worker-1", agent_id="worker-1")
    chat.append_bot("instance:worker-1", "worker-1", 3, "Hel", "streaming")
    with sqlite3.connect(tmp_path / ".cache/dashboard/chat.sqlite3") as db:
        db.execute("DROP TABLE chat_projection_cursors")
        db.execute("PRAGMA user_version = 2")
    chat = open_chat(tmp_path)
    store = FakeStore(
        [_session()],
        {
            "worker-1": [
                _event(1, "text", {"text": "old"}),
                _event(3, "text_delta", {"text": "Hel"}),
                _event(5, "text", {"text": "Hello"}),
            ]
        },
    )
    asyncio.run(InstanceThreads(chat).refresh(FakeSupervisor(tmp_path, store)))
    assert store.event_cursors[0] == ("worker-1", 2)
    assert _bot_rows(chat)[-1] == (3, "Hello", "final")
    assert len(_bot_rows(chat)) == 1
