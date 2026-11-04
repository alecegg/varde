# pyright: reportArgumentType=false, reportGeneralTypeIssues=false
import asyncio
import hashlib
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from varde_data.config import DataConfig, load_data_config
from varde_data.open import open_data
from varde_data.records.messages import Delivery, Message, NewMessage
from varde_data.version import Version
from varde_runner.cache import SingleFlightCache
from varde_runner.decisions import DecisionStore
from varde_runner.open_decisions import open_decision_items
from varde_runner.plan_reads import PlanReads
from varde_runner.varde_cli import VardeCLI
from varde_runner.web import app as dashboard_module
from varde_runner.web.app import (
    NEEDS_YOU_CACHE_TTL,
    DashboardData,
    _dashboard_watched_roots,
    _dashboard_working_dir,
    _invalidate_dashboard,
    _mailbox_payload,
    _sse_file_poll_due,
    _sse_orchestrators,
    _sse_projection_due,
    _sse_refresh_due,
    _sse_source_signature,
    create_app,
)
from varde_runner.web.cache import InboxStoreCache, watched_files_signature


def message(message_id, sender="worker", kind="needs-user"):
    return {
        "id": message_id,
        "ts": "2026-10-20T10:00:00Z",
        "from": sender,
        "to": "main",
        "kind": kind,
        "text": message_id,
    }


async def _get_asgi_status(app, path):
    response_messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        response_messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"localhost:8765")],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8765),
        },
        receive,
        send,
    )
    return next(
        item for item in response_messages if item["type"] == "http.response.start"
    )["status"]


def test_inbox_store_cache_invalidates_when_ack_is_appended(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VARDE_DATA_MESSAGES_BACKEND", "files")
    config = load_data_config()
    repository = open_data(tmp_path, config).messages
    stored = repository.append(NewMessage("worker", "main", "needs-user", "q1"))
    cache = InboxStoreCache(tmp_path)

    first = cache.read()
    item = {
        "msg_id": stored.id,
        "sender": "worker",
        "kind": "needs-user",
        "state": "pending",
        "ts": stored.ts,
    }
    assert open_decision_items(
        [item], first.messages, first.acknowledged_ids, {"worker"}, set()
    ) == [item]

    repository.record_delivery(
        Delivery(stored.id or "", "main", "session", "cli", "delivered", "now")
    )
    repository.ack("main", stored.id or "", now="now")
    second = cache.read()
    assert second.acknowledged_ids == {stored.id}
    assert (
        open_decision_items(
            [item], second.messages, second.acknowledged_ids, {"worker"}, set()
        )
        == []
    )


def test_inbox_cache_detects_repository_version_after_message_replace(tmp_path):
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    messages = inbox / "messages.jsonl"
    first = message("old")
    messages.write_text(json.dumps(first) + "\n")
    cache = InboxStoreCache(tmp_path)
    assert cache.read().messages[0]["id"] == "old"
    messages.write_text("")
    assert cache.read().messages == []
    messages.write_text(json.dumps(first) + "\n")
    assert cache.read().messages[0]["id"] == "old"
    replacement = message("new")
    assert len(json.dumps(replacement) + "\n") == len(json.dumps(first) + "\n")
    old_stat = messages.stat()
    replacement_path = inbox / "replacement"
    replacement_path.write_text(json.dumps(replacement) + "\n")
    replacement_path.replace(messages)
    os.utime(messages, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert cache.read().messages[0]["id"] == "new"


def test_inbox_read_error_keeps_last_good_and_retries(tmp_path, monkeypatch):
    repository = open_data(tmp_path, DataConfig()).messages
    repository.append(NewMessage("worker", "main", "info", "kept"))
    cache = InboxStoreCache(tmp_path)
    good = cache.read()
    original = cache.repository.read_all

    def unreadable():
        raise PermissionError("denied")

    repository.append(NewMessage("worker", "main", "info", "new"))
    monkeypatch.setattr(cache.repository, "read_all", unreadable)
    assert cache.read() is good
    monkeypatch.setattr(cache.repository, "read_all", original)
    assert [row["text"] for row in cache.read().messages] == ["kept", "new"]


def test_inbox_cache_reuses_snapshot_when_repository_version_is_unchanged(tmp_path):
    cache = InboxStoreCache(tmp_path)
    cache._cache._clock_ns = lambda: time.time_ns() + 5_000_000_000
    original = cache.repository.read_all
    calls = []

    def observe():
        calls.append(True)
        return original()

    cache.repository.read_all = observe
    first = cache.read()
    assert cache.read() is first
    assert calls == [True]


def test_inbox_cache_bounds_consistent_read_retries(tmp_path, monkeypatch):
    cache = InboxStoreCache(tmp_path)
    last_good = cache.read()
    calls = 0

    def moving_version():
        nonlocal calls
        calls += 1
        return Version(calls)

    monkeypatch.setattr(cache._cache, "_version", moving_version)
    assert cache.read() is last_good
    assert calls == 7


def test_dashboard_working_dir_prefers_cli_environment(tmp_path):
    cli = SimpleNamespace(
        cwd=tmp_path / "cwd", env={"VARDE_WORKING_DIR": str(tmp_path / "working")}
    )
    assert _dashboard_working_dir(cli) == (tmp_path / "working").resolve()


def test_single_flight_cache_serves_last_good_on_error_and_isolates_keys():
    cache = SingleFlightCache()
    assert cache.get("good", 0, lambda: "last-good") == "last-good"
    assert (
        cache.get("good", 0, lambda: (_ for _ in ()).throw(RuntimeError()))
        == "last-good"
    )
    assert cache.get("other", 1, lambda: "separate") == "separate"


def test_single_flight_cache_refreshes_distinct_keys_in_parallel():
    cache = SingleFlightCache()
    barrier = Barrier(2)

    def load(key):
        barrier.wait(timeout=1)
        return key

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda key: cache.get(key, 1, lambda: load(key)), ("a", "b"))
        )
    assert results == ["a", "b"]


def test_single_flight_cache_negatively_caches_cold_errors():
    cache = SingleFlightCache()
    calls = []

    def fail():
        calls.append(1)
        raise RuntimeError("unavailable")

    with pytest.raises(RuntimeError, match="unavailable"):
        cache.get("failure", 1, fail, negative_ttl=0.1)
    with pytest.raises(RuntimeError, match="unavailable"):
        cache.get("failure", 1, fail, negative_ttl=0.1)
    assert len(calls) == 1


def test_single_flight_cache_cold_error_expires_at_negative_ttl(monkeypatch):
    cache = SingleFlightCache()
    now = [10.0]
    monkeypatch.setattr("varde_runner.cache.time.monotonic", lambda: now[0])
    with pytest.raises(RuntimeError):
        cache.get(
            "failure",
            100,
            lambda: (_ for _ in ()).throw(RuntimeError()),
            negative_ttl=2,
        )
    now[0] = 11.9
    with pytest.raises(RuntimeError):
        cache.get("failure", 100, lambda: "recovered", negative_ttl=2)
    now[0] = 12.1
    assert cache.get("failure", 100, lambda: "recovered", negative_ttl=2) == "recovered"


def test_watched_signature_includes_sqlite_wal(tmp_path):
    database = tmp_path / "workitems.sqlite3"
    wal = tmp_path / "workitems.sqlite3-wal"
    database.touch()
    wal.write_text("first")
    before = watched_files_signature((database, wal))
    wal.write_text("second")
    assert watched_files_signature((database, wal)) != before


def test_sse_heartbeat_refreshes_agents_when_files_are_static():
    responses = [[{"agent": {"id": "first"}}], [{"agent": {"id": "second"}}]]
    snapshot_builds = []

    async def list_agents():
        return responses.pop(0)

    def read_plan_status():
        return {"plans": []}

    dashboard = DashboardData(
        SimpleNamespace(
            read_plan_status=read_plan_status,
            read_plan_watch=lambda: {"events": []},
        ),
        SimpleNamespace(last_messages=[], project=list),
        SimpleNamespace(),
        list_agents,
    )

    async def no_needs_you():
        return []

    dashboard.needs_you_threads = no_needs_you
    build_snapshot = dashboard._build_snapshot

    async def count_snapshot_builds():
        snapshot_builds.append(1)
        return await build_snapshot()

    dashboard._build_snapshot = count_snapshot_builds

    async def run():
        initial = await _sse_orchestrators(dashboard)
        initial_snapshot_builds = len(snapshot_builds)
        unchanged = await _sse_orchestrators(dashboard)
        assert len(snapshot_builds) == initial_snapshot_builds
        files = (("plans/plan.md", 1, 1, 1, 1),)
        assert not _sse_refresh_due(files, files, 10, 24.9)
        assert _sse_refresh_due(files, files, 10, 25)
        assert _sse_file_poll_due(0, 10)
        assert not _sse_file_poll_due(10, 39.9)
        assert _sse_file_poll_due(10, 40)
        assert _sse_projection_due(files, None)
        assert not _sse_projection_due(files, files)
        assert _sse_projection_due(((*files[0][:-1], 2),), files)
        dashboard.agents_loaded_at = 0
        refreshed = await _sse_orchestrators(dashboard)
        assert initial["agents"][0]["id"] == "first"
        assert unchanged["agents"][0]["id"] == "first"
        assert refreshed["agents"][0]["id"] == "second"
        assert len(snapshot_builds) > initial_snapshot_builds

    asyncio.run(run())


def test_sse_file_change_invalidates_cached_plan_data(tmp_path):
    plan_path = tmp_path / "plans" / "plan.md"
    plan_path.parent.mkdir()
    plan_path.write_text("old")

    class CLI:
        def read_plan_status(self):
            return {"plans": [{"status": plan_path.read_text()}]}

    dashboard = DashboardData(CLI(), None, None, None)
    before = watched_files_signature((plan_path.parent,))
    assert dashboard.plan_status()["plans"][0]["status"] == "old"
    plan_path.write_text("new")
    changed = watched_files_signature((plan_path.parent,))
    assert changed != before
    _invalidate_dashboard(dashboard)
    assert dashboard.plan_status()["plans"][0]["status"] == "new"


def test_sse_uses_cached_source_versions_instead_of_walking_trees(tmp_path):
    working = tmp_path / "working"
    working.mkdir()
    reads = PlanReads(working, working, {"VARDE_PLANS_BACKEND": "sqlite"})
    roots = _dashboard_watched_roots(
        tmp_path / "data", working, watch_plans=False, watch_inbox=False
    )
    assert working / "plans" not in roots
    assert working / ".cache" / "inbox" not in roots

    reads.generation = 1
    first = _sse_source_signature((), reads, "inbox-v1")
    reads.generation = 2
    second = _sse_source_signature((), reads, "inbox-v2")
    assert first != second


def test_inbox_store_cache_assigns_cli_compatible_ids_to_legacy_messages(tmp_path):
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    row = message("ignored")
    row.pop("id")
    line = json.dumps(row).encode() + b"\n"
    (inbox / "messages.jsonl").write_bytes(line)

    snapshot = InboxStoreCache(tmp_path).read()

    expected_id = "m-" + hashlib.sha256(b"0" + line.rstrip(b"\r\n")).hexdigest()[:8]
    assert snapshot.messages == [{**row, "id": expected_id}]


def test_inbox_store_cache_ignores_partial_trailing_message(tmp_path):
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    complete = message("complete")
    content = (json.dumps(complete) + "\n{" + '"id":"partial"').encode()
    (inbox / "messages.jsonl").write_bytes(content)
    assert [row["id"] for row in InboxStoreCache(tmp_path).read().messages] == [
        "complete"
    ]


def test_inbox_store_cache_matches_open_item_semantics_for_synthetic_store(
    tmp_path, monkeypatch
):
    repository = open_data(tmp_path, DataConfig()).messages
    records = {
        "open": repository.append(
            NewMessage("worker-open", "main", "needs-user", "open")
        ),
        "replied": repository.append(
            NewMessage(
                "worker-replied",
                "main",
                "needs-user",
                "replied",
                ts="2030-10-24T10:00:00Z",
            )
        ),
        "acked": repository.append(
            NewMessage("worker-acked", "main", "needs-user", "acked")
        ),
        "unbound": repository.append(
            NewMessage("worker-unbound", "main", "needs-user", "unbound")
        ),
        "concluded": repository.append(
            NewMessage("worker-concluded", "main", "needs-user", "concluded")
        ),
        "done": repository.append(NewMessage("worker-done", "main", "info", "done")),
    }
    acknowledged = records["acked"]
    repository.record_delivery(
        Delivery(acknowledged.id or "", "main", "session", "cli", "delivered", "now")
    )
    repository.ack("main", acknowledged.id or "", now="now")
    repository.mark_concluded("worker-concluded")
    repository.append(
        NewMessage(
            "main",
            "worker-replied",
            "info",
            "reply",
            # Fixed dates keep reply ordering independent of the test clock.
            ts="2030-10-25T10:01:00Z",
        )
    )
    cache = InboxStoreCache(tmp_path)
    snapshot = cache.read()
    items = [
        {
            "msg_id": row.id,
            "sender": row.from_,
            "kind": row.kind,
            "state": "pending",
            "ts": row.ts,
        }
        for row in records.values()
    ]

    bound_addresses = {
        "worker-open",
        "worker-replied",
        "worker-acked",
        "worker-concluded",
        "worker-done",
    }

    def no_subprocess(*args, **kwargs):
        raise AssertionError("message cache must not spawn subprocesses")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    actual = open_decision_items(
        items,
        snapshot.messages,
        snapshot.acknowledged_ids,
        bound_addresses,
        snapshot.concluded_addresses,
    )
    assert [item["msg_id"] for item in actual] == [records["open"].id]


def test_dashboard_open_items_never_calls_subprocess(tmp_path, monkeypatch):
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    row = message("q1", "worker")
    (inbox / "messages.jsonl").write_text(json.dumps(row) + "\n")
    (inbox / "deliveries.jsonl").write_text("")
    cache = InboxStoreCache(tmp_path)

    class CLI:
        def read_address_bindings(self):
            return [{"address": "worker", "plan_id": "cache-plan"}]

        def read_plan_status(self):
            return {
                "plans": [
                    {"id": "cache-plan", "status": "active", "assigned_to": "worker"}
                ]
            }

        def read_plan(self):
            return self.read_plan_status()

    def no_subprocess(*args, **kwargs):
        raise AssertionError("open mailbox items must not spawn subprocesses")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    dashboard = DashboardData(
        CLI(),
        SimpleNamespace(last_messages=[row], project=list),
        SimpleNamespace(),
        list,
        inbox_cache=cache,
    )
    asyncio.run(dashboard.orchestrators())
    item = {
        "msg_id": "q1",
        "sender": "worker",
        "kind": "needs-user",
        "state": "pending",
        "ts": row["ts"],
    }
    assert asyncio.run(dashboard.open_mailbox_items([item])) == [item]


def test_real_cli_mailbox_path_uses_cache_when_subprocess_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_DATA_MESSAGES_BACKEND", "files")
    working = tmp_path / "working"
    inbox = working / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    row = message("cached", "worker")
    (inbox / "messages.jsonl").write_text(json.dumps(row) + "\n")
    (inbox / "deliveries.jsonl").write_text("")
    env = {
        "VARDE_WORKING_DIR": str(working),
        "VARDE_RUNNER_CONFIG_DIR": str(tmp_path / "config"),
    }
    cli = VardeCLI(cwd=tmp_path, env=env)

    def fake_run(args, **kwargs):
        if args[1:3] == ["plan", "watch"]:
            stdout = '{"kind":"snapshot","events":[]}\n'
        elif args[1:3] == ["plan", "status"]:
            stdout = (
                '{"data":{"plans":[{"id":"cache-plan","status":"active",'
                '"assigned_to":"worker","owner":"test","tasks":[]}]}}'
            )
        elif args[1:4] == ["msg", "address", "list"]:
            stdout = (
                '{"data":{"bindings":[{"address":"worker","plan_id":"cache-plan"}]}}'
            )
        elif args[1:3] == ["msg", "status"]:
            stdout = '{"data":{"messages":[]}}'
        elif args[1:3] == ["setup", "paths"]:
            stdout = json.dumps({"data": {"working": str(working)}})
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cli.read_address_bindings = lambda: [{"address": "worker", "plan_id": "cache-plan"}]
    app = create_app(data_dir=tmp_path / "runner", cli=cli, bound_port=8765)
    dashboard = app.state.dashboard
    dashboard.plan_reads = None
    cli.plan_reads = None
    dashboard.address_bindings()
    dashboard.plan_status()
    dashboard.plan_watch()
    dashboard.paseo_agents = list
    asyncio.run(dashboard.orchestrators())

    def no_subprocess(*args, **kwargs):
        raise AssertionError("warm mailbox path must not invoke subprocess.run")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    from test_web import app_request

    response = app_request(app, "GET", "/api/mailbox")
    assert response.status_code == 200
    assert [entry["msg_id"] for entry in response.json()["open"]] == ["cached"]


def test_dashboard_uses_enabled_plan_reads_without_cli_fallback(tmp_path, monkeypatch):
    working = tmp_path / "working"
    plan = working / "plans" / "indexed-plan" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "---\ntype: plan\nid: indexed-plan\ntitle: Indexed plan\nstatus: active\n---\n",
        encoding="utf-8",
    )
    env = {
        "VARDE_WORKING_DIR": str(working),
        "VARDE_PLANS_BACKEND": "sqlite",
        "VARDE_RUNNER_CONFIG_DIR": str(tmp_path / "config"),
    }
    cli = VardeCLI(cwd=working, env=env)

    def unexpected_cli_read():
        raise AssertionError("enabled plan reads must serve dashboard status")

    cli.read_plan_status = unexpected_cli_read
    app = create_app(data_dir=tmp_path / "dashboard", cli=cli, agents=list)
    reads = app.state.dashboard.plan_reads
    assert reads is not None and reads.enabled
    reads.refresh_once()

    plans = app.state.dashboard.plan_status()["plans"]

    assert [row["id"] for row in plans] == ["indexed-plan"]


def test_inbox_store_cache_handles_2000_messages_without_subprocess(
    tmp_path, monkeypatch
):
    repository = open_data(tmp_path, DataConfig()).messages
    records = [
        Message(
            "2026-10-20T10:00:00Z",
            f"worker-{index % 8}",
            "main",
            "needs-user",
            f"q{index}",
            id=f"m-{index:08x}",
        )
        for index in range(2000)
    ]
    repository.import_messages(records)
    cache = InboxStoreCache(tmp_path)

    def no_subprocess(*args, **kwargs):
        raise AssertionError("mailbox cache must not spawn subprocesses")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    cache._cache._clock_ns = lambda: time.time_ns() + 5_000_000_000
    first = cache.read()
    assert len(first.messages) == 2000
    open_items = open_decision_items(
        [
            {
                "msg_id": row["id"],
                "sender": row["from"],
                "kind": row["kind"],
                "state": "pending",
                "ts": row["ts"],
            }
            for row in first.messages
        ],
        first.messages,
        first.acknowledged_ids,
        {f"worker-{index}" for index in range(8)},
        set(),
    )
    reads = 0
    original_read_all = cache.repository.read_all

    def counted_read_all():
        nonlocal reads
        reads += 1
        return original_read_all()

    cache.repository.read_all = counted_read_all
    assert cache.read() is first
    assert reads == 0
    open_decision_items(
        [
            {
                "msg_id": row["id"],
                "sender": row["from"],
                "kind": row["kind"],
                "state": "pending",
                "ts": row["ts"],
            }
            for row in first.messages
        ],
        first.messages,
        first.acknowledged_ids,
        {f"worker-{index}" for index in range(8)},
        set(),
    )
    assert len(open_items) == 2000
    payload_start = time.perf_counter()
    payload = _mailbox_payload(
        [
            {"kind": "needs-user", "state": "pending", "msg_id": row["id"]}
            for row in first.messages
        ]
    )
    assert len(payload["open"]) == 2000
    assert time.perf_counter() - payload_start < 0.05


def test_single_flight_cache_shares_concurrent_refresh():
    cache = SingleFlightCache()
    barrier = Barrier(4)
    calls = []

    def load():
        calls.append(1)
        time.sleep(0.02)
        return {"ok": True}

    def get():
        barrier.wait()
        return cache.get("value", 3, load)

    with ThreadPoolExecutor(max_workers=4) as executor:
        values = list(executor.map(lambda _: get(), range(4)))

    assert values == [{"ok": True}] * 4
    assert len(calls) == 1


def test_single_flight_cache_loads_when_monotonic_time_is_below_ttl(monkeypatch):
    cache = SingleFlightCache()
    monkeypatch.setattr("varde_runner.cache.time.monotonic", lambda: 1.0)

    assert cache.get("value", 3, lambda: "loaded") == "loaded"


def test_single_flight_cache_serves_stale_and_refreshes_once():
    cache = SingleFlightCache()
    assert cache.get_swr("value", 0, lambda: "old") == "old"
    started = Event()
    release = Event()
    calls = []

    def refresh():
        calls.append(1)
        started.set()
        release.wait(timeout=1)
        return "new"

    assert cache.get_swr("value", 0, refresh) == "old"
    assert started.wait(timeout=1)
    assert cache.get_swr("value", 0, refresh) == "old"
    assert len(calls) == 1
    release.set()
    deadline = time.monotonic() + 1
    while cache.get_swr("value", 1, refresh) != "new" and time.monotonic() < deadline:
        time.sleep(0.001)
    assert len(calls) == 1


def test_single_flight_cache_invalidate_starts_refresh():
    cache = SingleFlightCache()
    assert cache.get_swr("value", 10, lambda: "old") == "old"
    refreshed = Event()

    def loader():
        refreshed.set()
        return "new"

    # Register the refresh loader, then invalidate the cached value.
    assert cache.get_swr("value", 10, loader) == "old"
    cache.invalidate("value")
    assert refreshed.wait(timeout=1)


def test_single_flight_cache_drops_refresh_invalidated_in_flight():
    cache = SingleFlightCache()
    assert cache.get_swr("value", 10, lambda: "initial") == "initial"
    started = Event()
    release = Event()

    def stale_loader():
        started.set()
        release.wait(timeout=1)
        return "stale"

    assert cache.get_swr("value", 0, stale_loader) == "initial"
    assert started.wait(timeout=1)
    cache.invalidate("value", refresh=False)
    assert cache.get("value", 10, lambda: "fresh") == "fresh"
    release.set()
    time.sleep(0.01)
    assert cache.peek("value") == "fresh"


def test_single_flight_cache_logs_failed_background_refresh(caplog):
    cache = SingleFlightCache()
    assert cache.get_swr("value", 10, lambda: "cached") == "cached"
    finished = Event()

    def fail():
        finished.set()
        raise RuntimeError("refresh failed")

    cache.get_swr("value", 0, fail)
    assert finished.wait(timeout=1)
    deadline = time.monotonic() + 1
    while (
        "Background cache refresh failed" not in caplog.text
        and time.monotonic() < deadline
    ):
        time.sleep(0.001)
    assert "Background cache refresh failed for value" in caplog.text


def test_dashboard_lifespan_prewarm_reads(tmp_path):
    app = create_app(
        data_dir=tmp_path / "runner",
        cli=SimpleNamespace(
            send=lambda *_args, **_kwargs: {},
            read_messages=list,
            read_plan=lambda: {"plans": []},
        ),
        decisions=DecisionStore(
            tmp_path / "decisions", send=lambda *_args, **_kwargs: {}
        ),
    )
    dashboard = app.state.dashboard
    reads = []

    async def mailbox_items():
        reads.append("mailbox")
        return []

    dashboard.mailbox_items = mailbox_items
    dashboard.plan_status = lambda: reads.append("plan_status") or {}
    dashboard.plan_watch = lambda: reads.append("plan_watch") or {}
    dashboard.address_bindings = lambda: reads.append("address_bindings") or []

    async def run():
        async with app.router.lifespan_context(app):
            await dashboard.prewarm_task
            assert set(reads) == {
                "mailbox",
                "plan_status",
                "plan_watch",
                "address_bindings",
            }
            assert dashboard.snapshot_loaded_at > 0

    asyncio.run(run())


def test_dashboard_prewarm_failure_does_not_prevent_startup(tmp_path, caplog):
    app = create_app(
        data_dir=tmp_path / "runner",
        cli=SimpleNamespace(
            send=lambda *_args, **_kwargs: {},
            read_messages=list,
            read_plan=lambda: {"plans": []},
        ),
        decisions=DecisionStore(
            tmp_path / "decisions", send=lambda *_args, **_kwargs: {}
        ),
    )

    async def fail_prewarm():
        raise RuntimeError("warm failure")

    sibling_cancelled = []

    async def wait_for_prewarm():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            sibling_cancelled.append(True)
            raise

    app.state.dashboard.mailbox_items = fail_prewarm
    app.state.dashboard.orchestrators = wait_for_prewarm

    yielded = []

    async def run():
        async with app.router.lifespan_context(app):
            yielded.append(True)
            await app.state.dashboard.prewarm_task

    asyncio.run(run())
    assert yielded == [True]
    assert sibling_cancelled == [True]
    assert "Dashboard cache prewarm failed" in caplog.text
    assert app.state.dashboard.degraded_sources() == ["startup_prewarm"]


def test_dashboard_prewarm_timeout_does_not_prevent_startup(
    tmp_path, monkeypatch, caplog
):
    app = create_app(
        data_dir=tmp_path / "runner",
        cli=SimpleNamespace(
            send=lambda *_args, **_kwargs: {},
            read_messages=list,
            read_plan=lambda: {"plans": []},
        ),
        decisions=DecisionStore(
            tmp_path / "decisions", send=lambda *_args, **_kwargs: {}
        ),
    )

    async def hang():
        await asyncio.Event().wait()

    app.state.dashboard.mailbox_items = hang
    monkeypatch.setattr(dashboard_module, "DASHBOARD_PREWARM_TIMEOUT", 0.01)
    yielded = []

    async def run():
        async with app.router.lifespan_context(app):
            yielded.append(True)
            await app.state.dashboard.prewarm_task

    asyncio.run(run())
    assert yielded == [True]
    assert "Dashboard cache prewarm timed out" in caplog.text
    assert app.state.dashboard.degraded_sources() == ["startup_prewarm"]


def test_dashboard_reports_queue_migration_pending(tmp_path):
    working = tmp_path / "working"
    marker = working / ".cache/data/queue.version"
    marker.parent.mkdir(parents=True)
    marker.write_text("3\n", encoding="ascii")
    app = create_app(
        data_dir=tmp_path / "runner",
        cli=SimpleNamespace(
            cwd=working,
            send=lambda *_args, **_kwargs: {},
            read_messages=list,
            read_plan=lambda: {"plans": []},
        ),
        decisions=DecisionStore(
            tmp_path / "decisions", send=lambda *_args, **_kwargs: {}
        ),
    )

    assert app.state.dashboard.degraded_sources() == [
        "queue migration pending: run varde plan queue merge-role-inbox"
    ]


def test_dashboard_prewarm_runs_in_background_and_is_cancelled_on_shutdown(tmp_path):
    app = create_app(
        data_dir=tmp_path / "runner",
        cli=SimpleNamespace(
            send=lambda *_args, **_kwargs: {},
            read_messages=list,
            read_plan=lambda: {"plans": []},
        ),
        decisions=DecisionStore(
            tmp_path / "decisions", send=lambda *_args, **_kwargs: {}
        ),
    )
    dashboard = app.state.dashboard
    state = {}

    async def hang():
        state["started"].set()
        await asyncio.Event().wait()

    dashboard.mailbox_items = hang

    async def run():
        state["started"] = asyncio.Event()
        async with asyncio.timeout(2):
            async with app.router.lifespan_context(app):
                await state["started"].wait()
                assert not dashboard.prewarm_task.done()
                assert dashboard.degraded_sources() == []
        assert dashboard.prewarm_task.cancelled()
        assert dashboard.degraded_sources() == []

    asyncio.run(run())


def test_first_orchestrators_request_after_startup_is_within_budget(tmp_path):
    app = create_app(
        data_dir=tmp_path / "runner",
        cli=SimpleNamespace(
            send=lambda *_args, **_kwargs: {},
            read_messages=list,
            read_plan=lambda: {"plans": []},
        ),
        decisions=DecisionStore(
            tmp_path / "decisions", send=lambda *_args, **_kwargs: {}
        ),
        agents=list,
    )

    async def run():
        async with app.router.lifespan_context(app):
            started = time.monotonic()
            status = await _get_asgi_status(app, "/api/orchestrators")
            elapsed = time.monotonic() - started
            assert status == 200
            assert app.state.dashboard.snapshot_loaded_at > 0
            assert elapsed < 3

    asyncio.run(run())


def test_first_orchestrators_with_large_relay_state_does_not_spawn_subprocess(
    tmp_path, monkeypatch
):
    working = tmp_path / "working"
    relay = working / ".cache" / "inbox" / "relay"
    relay.mkdir(parents=True)
    now = time.time()
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    events = [
        {
            "event": "pushed",
            "at": stamp,
            "token_id": f"worker-{index}",
            "message_id": f"message-{index}",
        }
        for index in range(4500)
    ]
    events.append({"event": "waiting", "at": stamp, "token_id": "mail-token"})
    state = relay / "state.json"
    state.write_text(
        json.dumps({"current_mailman": "mail-token", "events": events}),
        encoding="utf-8",
    )
    assert state.stat().st_size >= 440_000

    def no_subprocess(*args, **kwargs):
        raise AssertionError("orchestrator snapshot must not spawn subprocesses")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    cli = SimpleNamespace(
        cwd=working,
        env={},
        read_messages=list,
        read_plan=lambda: {"plans": []},
        read_plan_status=lambda: {"plans": []},
        read_plan_watch=lambda: {"events": []},
        read_address_bindings=lambda: [
            {"address": "mailman", "wake_context": {"paseo_id": "mail-agent"}}
        ],
    )
    app = create_app(
        data_dir=tmp_path / "runner",
        cli=cli,
        decisions=DecisionStore(
            tmp_path / "decisions", send=lambda *_args, **_kwargs: {}
        ),
        agents=lambda: [{"agent": {"id": "mail-agent", "status": "running"}}],
    )

    async def run():
        async with app.router.lifespan_context(app):
            started = time.monotonic()
            status = await _get_asgi_status(app, "/api/orchestrators")
            elapsed = time.monotonic() - started
            assert status == 200
            assert elapsed < 3
            mailman = next(
                row
                for row in app.state.dashboard.snapshot["infrastructure"]
                if row["address"] == "mailman"
            )
            assert mailman["relay_alive"] is True

    asyncio.run(run())


def test_snapshot_refresh_after_ttl_reuses_swr_inputs(tmp_path):
    status_reads = []
    status_calls = []
    watch_calls = []

    def read_plan_status():
        status_calls.append(True)
        return {"plans": []}

    def read_plan_watch():
        watch_calls.append(True)
        return {"events": []}

    app = create_app(
        data_dir=tmp_path / "runner",
        cli=SimpleNamespace(
            send=lambda *_args, **_kwargs: {},
            read_messages=list,
            read_plan=lambda: {"plans": []},
            read_plan_status=read_plan_status,
            read_plan_watch=read_plan_watch,
            read_address_bindings=list,
            read_message_status=lambda: status_reads.append(True) or {},
        ),
        decisions=DecisionStore(
            tmp_path / "decisions", send=lambda *_args, **_kwargs: {}
        ),
        agents=list,
    )
    app.state.dashboard.inbox_cache = InboxStoreCache(tmp_path / "working")

    async def run():
        async with app.router.lifespan_context(app):
            dashboard = app.state.dashboard
            await dashboard.prewarm_task
            warm_status_reads = len(status_reads)
            warm_inputs = (len(status_calls), len(watch_calls))
            assert warm_status_reads == 0
            dashboard.snapshot_loaded_at -= 2.1
            started = time.monotonic()
            status = await _get_asgi_status(app, "/api/orchestrators")
            elapsed = time.monotonic() - started
            assert status == 200
            assert elapsed < 3
            assert len(status_reads) == warm_status_reads
            assert (len(status_calls), len(watch_calls)) == warm_inputs

    asyncio.run(run())


def test_dashboard_plan_status_shares_concurrent_refresh():
    barrier = Barrier(4)
    calls = []

    class CLI:
        def read_plan_status(self):
            calls.append(1)
            time.sleep(0.02)
            return {"plans": []}

    dashboard = DashboardData(CLI(), None, None, None)

    def read():
        barrier.wait()
        return dashboard.plan_status()

    with ThreadPoolExecutor(max_workers=4) as executor:
        values = list(executor.map(lambda _: read(), range(4)))

    assert values == [{"plans": []}] * 4
    assert len(calls) == 1


def test_watched_signature_changes_when_a_file_changes(tmp_path):
    source = tmp_path / "messages.jsonl"
    source.write_text("first\n")
    first = watched_files_signature((source,))

    source.write_text("second\n")

    assert watched_files_signature((source,)) != first


def test_agents_returns_stale_data_while_refresh_runs():
    async def list_agents():
        await asyncio.sleep(0.02)
        return [{"id": "fresh"}]

    dashboard = DashboardData(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        list_agents,
        cached_agents=[{"id": "stale"}],
        agents_loaded_at=0,
        agents_initialized=True,
    )

    async def run():
        start = time.perf_counter()
        stale = await dashboard.agents()
        elapsed = time.perf_counter() - start
        assert stale == [{"id": "stale"}]
        assert elapsed < 0.01
        assert dashboard.agents_refresh is not None
        await dashboard.agents_refresh
        assert dashboard.cached_agents == [{"id": "fresh"}]

    asyncio.run(run())


def test_agents_refresh_error_keeps_last_good_and_times_out(monkeypatch):
    async def unavailable():
        raise RuntimeError("sidecar offline")

    dashboard = DashboardData(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        unavailable,
        cached_agents=[{"id": "last-good"}],
        agents_initialized=True,
    )
    dashboard.agents_loaded_at = 0

    async def run():
        assert await dashboard.agents() == [{"id": "last-good"}]
        await dashboard.agents_refresh
        assert dashboard.cached_agents == [{"id": "last-good"}]
        assert dashboard.agents_error == "sidecar offline"

    asyncio.run(run())

    hanging = DashboardData(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        lambda: asyncio.sleep(60),
        cached_agents=[{"id": "stale"}],
        agents_initialized=True,
    )

    async def force_timeout(awaitable, *, timeout):
        assert timeout == 20
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("varde_runner.web.app.asyncio.wait_for", force_timeout)
    asyncio.run(hanging._refresh_agents())
    assert hanging.cached_agents == [{"id": "stale"}]
    assert hanging.agents_error == "TimeoutError"


def test_cold_request_needs_you_waits_for_first_snapshot():
    dashboard = DashboardData(None, None, None, None)
    dashboard.plan_reads = SimpleNamespace(enabled=True)  # pyright: ignore[reportAttributeAccessIssue]
    item = {"msg_id": "open"}

    async def slow_needs_you():
        await asyncio.sleep(0.05)
        return [item]

    dashboard.needs_you_threads = slow_needs_you

    async def run():
        first = await asyncio.gather(*(dashboard.request_needs_you() for _ in range(3)))
        assert first == [[item]] * 3
        dashboard.needs_you_snapshot = []
        dashboard.needs_you_loaded_at = time.monotonic() - NEEDS_YOU_CACHE_TTL
        assert await dashboard.request_needs_you() == []

    asyncio.run(run())
