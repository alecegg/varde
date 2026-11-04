from datetime import UTC, datetime, timedelta

from varde_runner.store import SessionStore


def test_wait_store_create_resolve_and_deadline(tmp_path):
    store = SessionStore(tmp_path)
    store.create_session("s1", "fake", {}, "builder")
    deadline = (datetime.now(UTC) + timedelta(minutes=2)).isoformat()

    assert store.create_wait(
        "approval:s1:r1", "s1", "approval", deadline, {"request_id": "r1"}
    )
    assert not store.create_wait("approval:s1:r1", "s1", "approval", deadline, {})
    assert store.earliest_deadline() == deadline
    assert store.pending_waits()[0]["payload"] == {"request_id": "r1"}
    assert store.resolve_wait("approval:s1:r1", "resolved", "approve")
    assert not store.resolve_wait("approval:s1:r1", "resolved", "approve")
    assert store.pending_waits() == []
    kinds = [event["kind"] for event in store.events_after("s1", 0)]
    assert kinds == ["wait_created", "wait_resolved"]


def test_earliest_deadline_ignores_past_and_missing_deadlines(tmp_path):
    store = SessionStore(tmp_path)
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    store.create_wait("wake:past", "s1", "wake", past, {})
    store.create_wait("wake:none", "s1", "wake", None, {})
    assert store.earliest_deadline() is None


def test_pushed_wake_message_ids_use_indexed_lookup(tmp_path):
    store = SessionStore(tmp_path)
    store.create_wait("wake:sent", "s1", "wake", payload={"message_ids": ["m1"]})
    store.resolve_wait("wake:sent", "resolved", "pushed")
    assert store.pushed_wake_message_ids({"m1", "m2"}) == {"m1"}


def test_wait_store_append_event_with_wait_is_atomic(tmp_path, monkeypatch):
    store = SessionStore(tmp_path)
    store.create_session("s1", "fake", {}, "builder")

    store.append_event_with_wait(
        "s1",
        "permission_requested",
        {"request_id": "r1"},
        wait_id="approval:s1:r1",
        kind="approval",
        payload={"request_id": "r1"},
    )

    assert [event["kind"] for event in store.events_after("s1", 0)] == [
        "permission_requested",
        "wait_created",
    ]
    assert len(store.pending_waits()) == 1

    def fail_create_wait(*_args, **_kwargs):
        raise RuntimeError("wait insert failed")

    monkeypatch.setattr(store, "_create_wait", fail_create_wait)
    try:
        store.append_event_with_wait(
            "s1",
            "permission_requested",
            {"request_id": "r2"},
            wait_id="approval:s1:r2",
            kind="approval",
            payload={"request_id": "r2"},
        )
    except RuntimeError as exc:
        assert str(exc) == "wait insert failed"
    else:
        raise AssertionError("expected the wait insert to fail")

    assert [event["kind"] for event in store.events_after("s1", 0)] == [
        "permission_requested",
        "wait_created",
    ]
    assert store.get_wait("approval:s1:r2") is None


def test_wake_wait_does_not_append_wait_events(tmp_path):
    store = SessionStore(tmp_path)
    store.create_session("s1", "fake", {}, "builder")

    assert store.create_wait("wake:a1", "s1", "wake", payload={"action_id": "a1"})
    assert store.resolve_wait("wake:a1", "resolved", "pushed")
    assert store.events_after("s1", 0) == []


def test_waits_by_kind_filters_state_and_orders_by_creation(tmp_path):
    store = SessionStore(tmp_path)
    store.create_wait("wake:first", "agent", "wake", payload={"message_ids": ["m1"]})
    store.resolve_wait("wake:first", "resolved", "pushed")
    store.create_wait("wake:second", "agent", "wake", payload={"message_ids": ["m2"]})
    store.create_wait(
        "approval:first", "agent", "approval", payload={"request_id": "r1"}
    )

    all_wakes = store.waits_by_kind("wake")
    pushed_wakes = store.waits_by_kind("wake", "resolved")
    pending_wakes = store.waits_by_kind("wake", "pending")

    assert [wait["wait_id"] for wait in all_wakes] == ["wake:first", "wake:second"]
    assert [wait["payload"] for wait in all_wakes] == [
        {"message_ids": ["m1"]},
        {"message_ids": ["m2"]},
    ]
    assert [wait["wait_id"] for wait in pushed_wakes] == ["wake:first"]
    assert [wait["wait_id"] for wait in pending_wakes] == ["wake:second"]
