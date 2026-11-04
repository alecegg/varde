from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from test_relay import FakeCLI, FakePlugin, action
from varde_runner.relay import RelayWorker
from varde_runner.store import SessionStore


def wait_for(store: SessionStore, wait_id: str) -> dict[str, Any]:
    wait = store.get_wait(wait_id)
    assert wait is not None
    return wait


class StoredPlugin(FakePlugin):
    def __init__(self, store):
        super().__init__()
        self.store = store


class ConfirmCheckingCLI(FakeCLI):
    def __init__(self, store, *, waits=None):
        super().__init__(waits=waits)
        self.store = store

    async def confirm(self, action, result, evidence, identity, *, harness):
        wait = self.store.get_wait(f"wake:{action}")
        assert wait is not None
        assert wait["decision"] == "pushed"
        await super().confirm(action, result, evidence, identity, harness=harness)


class FailOnceRenewCLI(ConfirmCheckingCLI):
    async def renew(self, action):
        if not self.renewed:
            self.renewed.append(action)
            raise RuntimeError("temporary renew failure")
        return await super().renew(action)


def test_pushed_wait_skips_send_after_restart(tmp_path):
    store = SessionStore(tmp_path)
    store.create_wait("wake:a", "agent", "wake", payload=action())
    store.resolve_wait("wake:a", "resolved", "pushed")
    store.close()
    store = SessionStore(tmp_path)
    plugin = StoredPlugin(store)
    cli = FakeCLI()
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"

    asyncio.run(worker._handle(action()))

    assert plugin.sent == []
    assert cli.confirmed == [("a", "pushed", "successful-send")]
    store.close()


def test_new_action_with_same_message_ids_dedupes_send(tmp_path):
    store = SessionStore(tmp_path)
    old = action("old")
    store.create_wait("wake:old", "agent", "wake", payload=old)
    store.resolve_wait("wake:old", "resolved", "pushed")
    store.close()
    store = SessionStore(tmp_path)
    plugin = StoredPlugin(store)
    cli = FakeCLI()
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"

    asyncio.run(worker._handle(action("new")))

    assert plugin.sent == []
    assert cli.confirmed == [("new", "pushed", "successful-send")]
    assert wait_for(store, "wake:new")["decision"] == "pushed"
    store.close()


def test_reoffered_subset_of_pushed_message_ids_dedupes_send(tmp_path):
    store = SessionStore(tmp_path)
    old = action("old")
    old["message_ids"] = ["m1", "m2"]
    store.create_wait("wake:old", "agent", "wake", payload=old)
    store.resolve_wait("wake:old", "resolved", "pushed")
    plugin = StoredPlugin(store)
    cli = ConfirmCheckingCLI(store)
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"
    offered = action("new")
    offered["message_ids"] = ["m1"]

    asyncio.run(worker._handle(offered))

    assert plugin.sent == []
    assert cli.confirmed == [("new", "pushed", "successful-send")]
    store.close()


def test_reoffered_superset_of_pushed_message_ids_is_sent(tmp_path):
    store = SessionStore(tmp_path)
    old = action("old")
    store.create_wait("wake:old", "agent", "wake", payload=old)
    store.resolve_wait("wake:old", "resolved", "pushed")
    plugin = StoredPlugin(store)
    cli = ConfirmCheckingCLI(store)
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"
    offered = action("new")
    offered["message_ids"] = ["m1", "m2"]

    asyncio.run(worker._handle(offered))

    assert plugin.sent == [("agent", "verbatim")]
    assert cli.confirmed == [("new", "pushed", "successful-send")]
    store.close()


def test_pending_wake_rearms_only_with_live_lease(tmp_path):
    store = SessionStore(tmp_path)
    pending = action()
    pending["expires_at"] = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    store.create_wait("wake:a", "agent", "wake", pending["expires_at"], pending)
    plugin = StoredPlugin(store)
    cli = ConfirmCheckingCLI(store)
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"

    asyncio.run(worker._rearm_wakes())

    assert plugin.sent == [("agent", "verbatim")]
    assert cli.confirmed == [("a", "pushed", "successful-send")]
    assert wait_for(store, "wake:a")["decision"] == "pushed"
    store.close()


def test_expired_pending_wake_is_not_rearmed(tmp_path):
    store = SessionStore(tmp_path)
    pending = action()
    pending["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    store.create_wait("wake:a", "agent", "wake", pending["expires_at"], pending)
    plugin = StoredPlugin(store)
    cli = FakeCLI()
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"

    asyncio.run(worker._rearm_wakes())

    assert plugin.sent == []
    assert wait_for(store, "wake:a")["state"] == "expired"
    assert cli.renewed == []
    store.close()


def test_busy_then_pushed_wait_survives_restart_before_confirm(tmp_path):
    store = SessionStore(tmp_path)
    plugin = StoredPlugin(store)
    plugin.status = "running"

    class CrashAfterSendCLI(FakeCLI):
        def __init__(self, store):
            super().__init__()
            self.store = store
            self.crash = True

        async def confirm(self, action, result, evidence, identity, *, harness):
            wait = self.store.get_wait(f"wake:{action}")
            if result == "pushed":
                assert wait["decision"] == "pushed"
            if self.crash and result == "pushed":
                self.crash = False
                raise RuntimeError("crash after send")
            await super().confirm(action, result, evidence, identity, harness=harness)

    cli = CrashAfterSendCLI(store)
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"
    item = action()
    asyncio.run(worker._handle(item))
    assert wait_for(store, "wake:a")["state"] == "pending"
    plugin.status = "idle"
    with pytest.raises(RuntimeError, match="crash after send"):
        asyncio.run(worker._handle(item))
    assert wait_for(store, "wake:a")["decision"] == "pushed"
    store.close()

    store = SessionStore(tmp_path)
    plugin = StoredPlugin(store)
    cli = ConfirmCheckingCLI(store)
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"
    asyncio.run(worker._handle(item))
    assert plugin.sent == []
    assert cli.confirmed == [("a", "pushed", "successful-send")]
    store.close()


def test_expired_renew_result_is_not_rearmed(tmp_path):
    store = SessionStore(tmp_path)
    pending = action()
    pending["expires_at"] = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    store.create_wait("wake:a", "agent", "wake", pending["expires_at"], pending)
    plugin = StoredPlugin(store)
    cli = FakeCLI()
    cli.renew_result = {"status": "expired"}
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"

    asyncio.run(worker._rearm_wakes())

    assert plugin.sent == []
    assert wait_for(store, "wake:a")["state"] == "expired"
    assert cli.renewed == ["a"]
    store.close()


def test_rearm_retries_after_renew_fails(tmp_path):
    store = SessionStore(tmp_path)
    pending = action()
    pending["expires_at"] = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    store.create_wait("wake:a", "agent", "wake", pending["expires_at"], pending)
    plugin = StoredPlugin(store)
    cli = FailOnceRenewCLI(
        store, waits=[{"actions": []}, RuntimeError("exit 64 superseded")]
    )
    worker = RelayWorker(cli, plugin, sleep=lambda _: asyncio.sleep(0))

    asyncio.run(worker.run())

    assert len(cli.renewed) == 3
    assert plugin.sent == [("agent", "verbatim")]
    assert cli.confirmed == [("a", "pushed", "successful-send")]
    assert wait_for(store, "wake:a")["decision"] == "pushed"
    store.close()


def test_send_then_crash_before_resolution_retries_at_least_once(tmp_path, monkeypatch):
    store = SessionStore(tmp_path)
    first_plugin = StoredPlugin(store)
    first_cli = FakeCLI()
    first_worker = RelayWorker(first_cli, first_plugin)
    first_worker.identity = "identity"
    resolve_wait = store.resolve_wait

    def crash_before_resolve(wait_id, state, decision):
        if wait_id == "wake:a" and decision == "pushed":
            raise RuntimeError("simulated crash after send")
        return resolve_wait(wait_id, state, decision)

    monkeypatch.setattr(store, "resolve_wait", crash_before_resolve)
    with pytest.raises(RuntimeError, match="simulated crash after send"):
        asyncio.run(first_worker._handle(action()))
    assert first_plugin.sent == [("agent", "verbatim")]
    assert wait_for(store, "wake:a")["state"] == "pending"

    monkeypatch.setattr(store, "resolve_wait", resolve_wait)
    store.close()
    store = SessionStore(tmp_path)
    plugin = StoredPlugin(store)
    cli = ConfirmCheckingCLI(store)
    worker = RelayWorker(cli, plugin)
    worker.identity = "identity"

    asyncio.run(worker._rearm_wakes())

    assert plugin.sent == [("agent", "verbatim")]
    assert cli.confirmed == [("a", "pushed", "successful-send")]
    assert wait_for(store, "wake:a")["decision"] == "pushed"
    store.close()
