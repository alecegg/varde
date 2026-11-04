import asyncio
import sqlite3
from functools import wraps

from varde_runner.store import SessionStore
from varde_runner.watch import WatchHub, snapshot


def _async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def _store(tmp_path):
    store = SessionStore(tmp_path)
    store.create_session("a", "codex", {}, "worker")
    store.create_session("b", "codex", {}, "worker")
    return store


def _stream_sequences(messages):
    sequences = []
    for message in messages:
        if message["type"] == "snapshot":
            sequences.extend(event["seq"] for event in message["events"])
        else:
            sequences.append(message["seq"])
    return sequences


def test_snapshot_contains_projection_and_limited_event_window(tmp_path):
    store = _store(tmp_path)
    for number in range(4):
        store.append_event("a", "status", {"n": number})
    store.create_wait("wait-a", "a", "approval", payload={"question": "ok?"})

    result = snapshot(store, "a", limit=2)

    assert [event["kind"] for event in result["events"]] == ["status", "wait_created"]
    assert result["truncated"] is True
    assert result["window_start"] == result["events"][0]["seq"]
    assert result["last_seq"] == 5
    assert result["pending_waits"][0]["wait_id"] == "wait-a"


def test_session_event_index_exists_for_fresh_and_migrated_stores(tmp_path):
    fresh = SessionStore(tmp_path / "fresh")
    fresh_indexes = {
        row["name"] for row in fresh.connection.execute("PRAGMA index_list(events)")
    }
    assert "events_session_seq" in fresh_indexes
    assert "events_session_created_at" in fresh_indexes
    query_plan = fresh.connection.execute(
        "EXPLAIN QUERY PLAN SELECT MAX(created_at) FROM events WHERE session_id=?",
        ("a",),
    ).fetchall()
    assert any("events_session_created_at" in row["detail"] for row in query_plan)
    assert fresh.connection.execute("PRAGMA user_version").fetchone()[0] == 7
    fresh.close()

    migrated_dir = tmp_path / "migrated"
    migrated_dir.mkdir()
    connection = sqlite3.connect(migrated_dir / "runner.sqlite3")
    connection.executescript(
        """CREATE TABLE sessions (
        id TEXT PRIMARY KEY, backend TEXT NOT NULL, ref TEXT NOT NULL,
        role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unknown',
        idle_status TEXT NOT NULL DEFAULT 'unknown',
        last_event_seq INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
        kind TEXT NOT NULL, payload TEXT NOT NULL);
        PRAGMA user_version = 3;"""
    )
    connection.close()

    migrated = SessionStore(migrated_dir)
    migrated_indexes = {
        row["name"] for row in migrated.connection.execute("PRAGMA index_list(events)")
    }
    assert "events_session_seq" in migrated_indexes
    assert "events_session_created_at" in migrated_indexes
    assert migrated.connection.execute("PRAGMA user_version").fetchone()[0] == 7
    migrated.close()


@_async_test
async def test_subscribe_precedes_snapshot_and_event_is_not_duplicated(
    tmp_path, monkeypatch
):
    import varde_runner.watch as watch_module

    store = _store(tmp_path)
    store.append_event("a", "before", {})
    hub = WatchHub()
    store.on_commit = hub.wake
    original = watch_module.snapshot
    inserted = False

    def append_before_snapshot(target, session_id, *, limit=200):
        nonlocal inserted
        assert hub._subscribers[session_id]
        if not inserted:
            inserted = True
            target.append_event(session_id, "between_subscribe_and_snapshot", {})
        return original(target, session_id, limit=limit)

    monkeypatch.setattr(watch_module, "snapshot", append_before_snapshot)
    stream = hub.watch(store, "a")
    initial = await anext(stream)
    assert initial["type"] == "snapshot"
    assert [event["kind"] for event in initial["events"]] == [
        "before",
        "between_subscribe_and_snapshot",
    ]

    store.append_event("a", "after_snapshot", {})
    event = await anext(stream)
    assert event["kind"] == "after_snapshot"
    await stream.aclose()

    expected = store.events_after("a", 0)
    assert _stream_sequences([initial, event]) == [row["seq"] for row in expected]


@_async_test
async def test_valid_cursor_replays_across_global_sequence_gaps(tmp_path):
    store = _store(tmp_path)
    first = store.append_event("a", "first", {})
    store.append_event("b", "interleave", {})
    third = store.append_event("a", "third", {})
    hub = WatchHub()

    stream = hub.watch(store, "a", after_seq=first)
    result = await anext(stream)
    assert result["type"] == "event"
    assert result["seq"] == third
    await stream.aclose()


@_async_test
async def test_truncated_stale_and_future_cursors_get_snapshot(tmp_path):
    store = _store(tmp_path)
    for n in range(201):
        store.append_event("a", "event", {"n": n})
    hub = WatchHub()

    stale = hub.watch(store, "a", after_seq=1)
    stale_message = await anext(stale)
    assert stale_message["type"] == "snapshot"
    assert stale_message["truncated"]
    assert stale_message["window_start"] > 1
    await stale.aclose()

    future = hub.watch(store, "a", after_seq=1000)
    assert (await anext(future))["type"] == "snapshot"
    await future.aclose()


@_async_test
async def test_slow_reader_resnapshots_and_sql_reads_use_page_limit(
    tmp_path, monkeypatch
):
    store = _store(tmp_path)
    hub = WatchHub()
    limits = []
    original = store.events_after

    def track_limit(session_id, seq, limit=None):
        limits.append(limit)
        return original(session_id, seq, limit)

    monkeypatch.setattr(store, "events_after", track_limit)
    stream = hub.watch(store, "a", queue_limit=3, page=1)
    assert (await anext(stream))["type"] == "snapshot"
    store.append_event("a", "one", {})
    store.append_event("a", "two", {})
    assert (await anext(stream))["kind"] == "one"
    assert (await anext(stream))["kind"] == "two"
    assert 1 in limits

    for n in range(4):
        store.append_event("a", "overflow", {"n": n})
    refreshed = await anext(stream)
    assert refreshed["type"] == "snapshot"
    await stream.aclose()


@_async_test
async def test_whole_stream_matches_store_across_overflow_resnapshot(
    tmp_path, monkeypatch
):
    import varde_runner.watch as watch_module

    store = _store(tmp_path)
    hub = WatchHub()
    store.on_commit = hub.wake
    original = watch_module.snapshot
    calls = 0

    def append_during_resnapshot(target, session_id, *, limit=200):
        nonlocal calls
        calls += 1
        if calls == 2:
            target.append_event(session_id, "before_resnapshot_read", {})
        result = original(target, session_id, limit=limit)
        if calls == 2:
            target.append_event(session_id, "after_resnapshot_read", {})
        return result

    monkeypatch.setattr(watch_module, "snapshot", append_during_resnapshot)
    stream = hub.watch(store, "a", queue_limit=2, page=1)
    messages = [await anext(stream)]
    for n in range(3):
        store.append_event("a", "overflow", {"n": n})
    messages.append(await anext(stream))
    messages.append(await anext(stream))
    await stream.aclose()

    assert calls == 2
    expected = store.events_after("a", 0)
    assert _stream_sequences(messages) == [row["seq"] for row in expected]


@_async_test
async def test_store_commit_wakes_watchers_for_direct_and_wait_events(tmp_path):
    store = _store(tmp_path)
    hub = WatchHub()
    store.on_commit = hub.wake
    stream = hub.watch(store, "a")
    await anext(stream)

    store.append_event("a", "parked", {})
    assert (await anext(stream))["kind"] == "parked"
    store.append_event("a", "resume", {})
    assert (await anext(stream))["kind"] == "resume"
    store.create_wait("wait", "a", "approval", payload={})
    assert (await anext(stream))["kind"] == "wait_created"
    store.resolve_wait("wait", "resolved", "approve")
    assert (await anext(stream))["kind"] == "wait_resolved"
    store.append_event_with_wait(
        "a", "parked", {}, wait_id="combined", kind="approval", payload={}
    )
    assert (await anext(stream))["kind"] == "parked"
    assert (await anext(stream))["kind"] == "wait_created"
    await stream.aclose()


@_async_test
async def test_wake_kind_wait_resolution_does_not_notify(tmp_path):
    store = _store(tmp_path)
    notifications = []
    store.on_commit = notifications.append
    store.create_wait("wake", "a", "wake", payload={})
    assert store.resolve_wait("wake", "resolved", "pushed")
    assert notifications == []


@_async_test
async def test_wake_without_subscribers_and_unsubscribe_on_close(tmp_path):
    store = _store(tmp_path)
    hub = WatchHub()
    hub.wake("a")
    stream = hub.watch(store, "a")
    await anext(stream)
    assert hub._subscribers["a"]
    await stream.aclose()
    assert "a" not in hub._subscribers
    hub.wake("a")
