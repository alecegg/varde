import sqlite3

import pytest
from varde_runner.store import SessionStore


def test_append_events_is_atomic_and_updates_sequence(tmp_path):
    store = SessionStore(tmp_path)
    store.create_session("s1", "paseo", {}, "planner")
    store.connection.execute(
        "CREATE TRIGGER fail_second_event BEFORE INSERT ON events "
        "WHEN NEW.kind = 'fail' BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
    )
    store.connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        store.append_events(
            "s1", [("text", {"text": "first"}), ("fail", {"text": "second"})]
        )
    assert store.events_after("s1", 0) == []
    session = store.get_session("s1")
    assert session is not None
    assert session["last_event_seq"] == 0
    store.close()

    reopened = SessionStore(tmp_path)
    assert reopened.events_after("s1", 0) == []
    session = reopened.get_session("s1")
    assert session is not None
    assert session["last_event_seq"] == 0


def test_append_events_round_trips_payloads_and_sequences(tmp_path):
    store = SessionStore(tmp_path)
    store.create_session("s1", "paseo", {}, "planner")
    payloads = [{"text": "hello", "nested": {"count": 1}}, {"call_id": "c1"}]

    seqs = store.append_events(
        "s1", [("text", payloads[0]), ("tool_intent", payloads[1])]
    )
    assert seqs[0] < seqs[1]
    assert [event["seq"] for event in store.events_after("s1", 0)] == seqs
    assert [event["payload"] for event in store.events_after("s1", 0)] == payloads
    session = store.get_session("s1")
    assert session is not None
    assert session["last_event_seq"] == seqs[-1]
    assert store.append_events("s1", []) == []


def test_abandoned_transaction_is_absent_after_reopen(tmp_path):
    store = SessionStore(tmp_path)
    store.create_session("s1", "paseo", {}, "planner")
    first_seq = store.append_event("s1", "status", {"status": "running"})
    store.close()

    abandoned = sqlite3.connect(tmp_path / "runner.sqlite3")
    abandoned.execute("BEGIN")
    abandoned.executemany(
        "INSERT INTO events(session_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
        [
            ("s1", "text", '{"text":"uncommitted one"}', "now"),
            ("s1", "text", '{"text":"uncommitted two"}', "now"),
        ],
    )
    abandoned.close()

    reopened = SessionStore(tmp_path)
    persisted = reopened.events_after("s1", 0)
    assert [event["seq"] for event in persisted] == [first_seq]
    later_seqs = reopened.append_events(
        "s1", [("text", {"text": "persisted one"}), ("text", {"text": "persisted two"})]
    )
    assert later_seqs[0] < later_seqs[1]
    assert later_seqs[0] > persisted[-1]["seq"]
    assert [event["seq"] for event in reopened.events_after("s1", 0)] == [
        first_seq,
        *later_seqs,
    ]


def test_open_intents_ignores_completed_and_legacy_tool_events(tmp_path):
    store = SessionStore(tmp_path)
    store.create_session("s1", "paseo", {}, "planner")
    seqs = store.append_events(
        "s1",
        [
            ("tool_intent", {"call_id": "open", "name": "a"}),
            ("tool_intent", {"call_id": "done", "name": "b"}),
            ("tool", {"call_id": "legacy"}),
            ("tool_result", {"call_id": "done", "result": "ok"}),
            ("tool_intent", {"call_id": "also-open", "name": "c"}),
        ],
    )

    open_intents = store.open_intents("s1")
    assert all(
        set(event) == {"seq", "session_id", "kind", "payload", "created_at"}
        for event in open_intents
    )
    assert [(event["seq"], event["kind"]) for event in open_intents] == [
        (seqs[0], "tool_intent"),
        (seqs[4], "tool_intent"),
    ]
    assert [event["payload"] for event in open_intents] == [
        {"call_id": "open", "name": "a"},
        {"call_id": "also-open", "name": "c"},
    ]


def test_open_intents_keeps_earliest_unresolved_record_per_call_id(tmp_path):
    store = SessionStore(tmp_path)
    store.create_session("s1", "paseo", {}, "planner")
    seqs = store.append_events(
        "s1",
        [
            ("tool_intent", {"call_id": "open", "update": 1}),
            ("tool_intent", {"call_id": "open", "update": 2}),
            ("tool_intent", {"call_id": "done", "update": 1}),
            ("tool_intent", {"call_id": "done", "update": 2}),
            ("tool_result", {"call_id": "done"}),
        ],
    )

    assert [(event["seq"], event["payload"]) for event in store.open_intents("s1")] == [
        (seqs[0], {"call_id": "open", "update": 1})
    ]


def test_normalized_paseo_tool_updates_pair_in_open_intents(tmp_path):
    from varde_runner.plugins.paseo import _normalize

    store = SessionStore(tmp_path)
    store.create_session("s1", "paseo", {}, "planner")
    payloads = [
        {"item": {"type": "tool_call", "callId": "call-1", "status": status}}
        for status in ("running", "running", "canceled")
    ]
    events = [
        _normalize("s1", {"event": "tool", "payload": payload}) for payload in payloads
    ]
    store.append_events("s1", [(event.kind, event.payload) for event in events])

    assert [event.kind for event in events] == [
        "tool_intent",
        "tool_intent",
        "tool_result",
    ]
    assert store.open_intents("s1") == []
