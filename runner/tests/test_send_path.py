from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path
from typing import cast

from test_web import app_request
from varde_runner.delivery import DeliveryLoop
from varde_runner.events import RunnerEvent
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.registry import SessionBinding, SessionRegistry
from varde_runner.relay import RelayCLIProtocol, RelayWorker
from varde_runner.supervisor import SendOutcome, Supervisor
from varde_runner.web.app import create_app


class FakePlugin:
    def __init__(self, *, interrupt: bool = False, idle: bool = True) -> None:
        self.capabilities = RunnerCapabilities(
            idle_status=True, respond=True, interrupt=interrupt
        )
        self.idle = idle
        self.sent: list[str] = []
        self.responses: list[tuple[str, str]] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.send_calls = 0
        self.interrupt_fails = False
        self.respond_fails = False
        self.idle_after_interrupt = False
        self.status = "idle" if idle else "running"

    async def start(self, spec: SessionSpec) -> SessionRef:
        return SessionRef("fake", "remote")

    async def send(self, ref: SessionRef, prompt: str) -> None:
        self.send_calls += 1
        self.entered.set()
        await self.release.wait()
        self.sent.append(prompt)
        self.status = "running"

    async def idle_status(self, ref: SessionRef) -> str:
        if ref.session_id == "gone":
            raise RuntimeError("Agent not found")
        return self.status

    async def inspect(self, ref: SessionRef) -> dict[str, object]:
        if ref.session_id == "archived":
            return {"status": "closed", "archived": True}
        return {"status": self.status, "archived": False}

    async def interrupt(self, ref: SessionRef) -> None:
        if self.interrupt_fails:
            raise RuntimeError("interrupt failed")
        if self.idle_after_interrupt:
            self.status = "idle"

    async def resume(self, ref: SessionRef) -> SessionRef:
        return ref

    async def events(self, ref: SessionRef):
        if False:
            yield RunnerEvent("status", ref.session_id)

    async def respond_permission(
        self, ref: SessionRef, request_id: str, decision: str
    ) -> None:
        if self.respond_fails:
            raise RuntimeError("respond failed")
        self.responses.append((request_id, decision))

    async def stop(self, ref: SessionRef) -> None:
        return None

    async def close(self) -> None:
        return None


def test_agent_capabilities_are_exposed_from_the_registry(
    tmp_path, monkeypatch
) -> None:
    plugin = FakePlugin()
    monkeypatch.setattr(
        "varde_runner.web.registry.PaseoPlugin.from_environment", lambda: plugin
    )
    app = create_app(data_dir=tmp_path / "dashboard")

    response = app_request(app, "GET", "/api/agents/capabilities")

    assert response.status_code == 200
    capabilities = response.json()
    assert set(capabilities) == {
        "codex-app-server",
        "pi",
        "claude-sdk",
        "pi-rpc",
        "opencode-http",
        "disabled",
    }
    assert capabilities["disabled"] == []
    assert all(
        capabilities[harness]["respond"]
        for harness in (
            "codex-app-server",
            "pi",
            "claude-sdk",
        )
    )
    assert not capabilities["pi-rpc"]["respond"]
    assert capabilities["opencode-http"]["respond"]


def test_supervisor_unmanaged_response_fails_closed_when_plugins_ambiguous(tmp_path):
    first, second = FakePlugin(), FakePlugin()
    registry = PluginRegistry()
    registry.register("harness-a", first, provider_key="provider-a")
    registry.register("harness-b", second, provider_key="provider-b")
    supervisor = Supervisor(tmp_path / "sessions", registry)

    assert asyncio.run(supervisor.respond("agent", "request", "allow")) == "ambiguous"
    assert (
        asyncio.run(supervisor.respond("agent", "request", "allow", "harness-b"))
        == "responded"
    )
    assert second.responses == [("request", "allow")]
    assert first.responses == []


def test_supervisor_unmanaged_response_uses_provider_for_shared_plugin(tmp_path):
    class RefPlugin(FakePlugin):
        def __init__(self):
            super().__init__()
            self.response_refs = []

        async def respond_permission(self, ref, request_id, decision):
            self.response_refs.append(ref)

    plugin = RefPlugin()
    registry = PluginRegistry()
    registry.register("harness-a", plugin, provider_key="provider-a")
    registry.register("harness-b", plugin, provider_key="provider-b")
    supervisor = Supervisor(tmp_path / "sessions", registry)

    assert asyncio.run(supervisor.respond("agent", "request", "allow")) == "responded"
    assert plugin.response_refs == [SessionRef("provider-a", "agent")]


def test_shared_plugin_serializes_harness_and_legacy_senders(tmp_path):
    async def run():
        plugin = FakePlugin()
        registry = PluginRegistry()
        registry.register("harness-a", plugin, provider_key="provider-a")
        registry.register("harness-b", plugin, provider_key="provider-b")
        supervisor = Supervisor(tmp_path / "sessions", registry)
        explicit = await supervisor._target("agent", "harness-a")
        legacy = await supervisor._target("agent", None)
        assert explicit is not None and legacy is not None
        assert explicit[3] == legacy[3] == (id(plugin), "agent")

    asyncio.run(run())


def test_concurrent_senders_serialize_and_second_is_busy(tmp_path: Path) -> None:
    async def run() -> None:
        plugin = FakePlugin()
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        session = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        await supervisor.record_event(session.session_id, "status", {"status": "idle"})
        waiting = asyncio.Event()

        class ObservedLock:
            def __init__(self):
                self.lock = asyncio.Lock()

            async def __aenter__(self):
                if self.lock.locked():
                    waiting.set()
                await self.lock.acquire()

            async def __aexit__(self, *_):
                self.lock.release()

        target = await supervisor._target(session.session_id, None)
        assert target is not None
        supervisor._send_locks[target[3]] = cast("asyncio.Lock", ObservedLock())
        first = asyncio.create_task(supervisor.send(session.session_id, "first"))
        await plugin.entered.wait()
        second = asyncio.create_task(supervisor.send(session.session_id, "second"))
        await asyncio.wait_for(waiting.wait(), timeout=1)
        assert plugin.send_calls == 1
        plugin.release.set()
        assert await first == SendOutcome.SENT
        assert await second == SendOutcome.SKIPPED_BUSY
        assert plugin.sent == ["first"]
        await supervisor.shutdown()

    asyncio.run(run())


def test_interrupt_timeout_does_not_submit_prompt(tmp_path: Path) -> None:
    async def run() -> None:
        plugin = FakePlugin(interrupt=True, idle=False)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.interrupt_timeout = 0.05
        session = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        assert (
            await supervisor.send_with_interrupt(session.session_id, "new")
            == SendOutcome.FAILED_INTERRUPT
        )
        assert plugin.sent == []
        await supervisor.shutdown()

    asyncio.run(run())


def test_interrupt_waits_for_idle_then_sends_and_fails_closed(tmp_path: Path) -> None:
    async def run() -> None:
        plugin = FakePlugin(interrupt=True, idle=False)
        plugin.idle_after_interrupt = True
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        session = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        plugin.release.set()
        assert (
            await supervisor.send_with_interrupt(session.session_id, "after")
            == SendOutcome.SENT
        )
        assert plugin.sent == ["after"]
        plugin.interrupt_fails = True
        assert (
            await supervisor.send_with_interrupt(session.session_id, "blocked")
            == SendOutcome.FAILED_INTERRUPT
        )
        no_interrupt = FakePlugin()
        no_interrupt.capabilities = RunnerCapabilities(idle_status=True)
        other = Supervisor(tmp_path / "other", {"fake": no_interrupt})
        other_session = await other.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        assert (
            await other.send_with_interrupt(other_session.session_id, "blocked")
            == SendOutcome.FAILED_INTERRUPT
        )
        await supervisor.shutdown()
        await other.shutdown()

    asyncio.run(run())


def test_fake_plugin_delivery_and_relay_use_supervisor_send(tmp_path: Path) -> None:
    async def run() -> None:
        plugin = FakePlugin()
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        session = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        await supervisor.record_event(session.session_id, "status", {"status": "idle"})
        bindings = SessionRegistry(tmp_path / "bindings.json")
        bindings.register(
            SessionBinding("address", "fake", "fake", "remote", "builder")
        )
        loop = DeliveryLoop(
            tmp_path / "claims.jsonl",
            bindings,
            supervisor,
            lambda: [{"id": "m1", "to": "address", "text": "mail"}],
        )
        plugin.release.set()
        assert await loop.deliver_once() == 1
        plugin.status = "idle"
        await supervisor.record_event(session.session_id, "status", {"status": "idle"})

        class CLI:
            async def renew(self, action_id):
                return {"status": "active"}

        worker = RelayWorker(cast("RelayCLIProtocol", CLI()), supervisor)
        result = await worker.deliver(
            {
                "action_id": "a1",
                "wake": {"harness": "fake", "agent_id": session.session_id},
                "prompt": "relay",
            }
        )
        assert result == ("pushed", "successful-send")
        assert plugin.sent == ["mail", "relay"]
        await supervisor.shutdown()

    asyncio.run(run())


def test_relay_legacy_paseo_id_uses_registry_plugin_when_unmanaged(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        plugin = FakePlugin()
        plugins = PluginRegistry()
        plugins.register("codex-app-server", plugin, provider_key="paseo")
        supervisor = Supervisor(tmp_path, plugins)
        plugin.release.set()

        class CLI:
            async def renew(self, action_id):
                return {"status": "active"}

        worker = RelayWorker(cast("RelayCLIProtocol", CLI()), supervisor)
        result = await worker.deliver(
            {
                "action_id": "legacy",
                "wake": {"paseo_id": "agent-a"},
                "prompt": "legacy prompt",
            }
        )
        assert result == ("pushed", "successful-send")
        assert plugin.sent == ["legacy prompt"]
        plugin.status = "unknown"
        unknown = await worker.deliver(
            {"action_id": "unknown", "wake": {"paseo_id": "agent-a"}, "prompt": "x"}
        )
        assert unknown == ("failed", "no-send")
        missing = await worker.deliver(
            {
                "action_id": "missing",
                "wake": {"harness": "codex-app-server", "agent_id": "gone"},
                "prompt": "x",
            }
        )
        assert missing == ("target-gone", "observed-result")
        plugin.status = "unknown"
        archived = await worker.deliver(
            {
                "action_id": "archived",
                "wake": {"paseo_id": "archived"},
                "prompt": "archive send",
            }
        )
        assert archived == ("pushed", "successful-send")
        assert plugin.sent[-1] == "archive send"
        await supervisor.shutdown()

    asyncio.run(run())


def test_legacy_agent_id_searches_registered_pi_and_claude_harnesses(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        class HarnessPlugin(FakePlugin):
            def __init__(self, agent_id: str) -> None:
                super().__init__()
                self.agent_id = agent_id

            async def inspect(self, ref: SessionRef) -> dict[str, object]:
                if ref.session_id != self.agent_id:
                    raise RuntimeError("Agent not found")
                return {"status": "idle", "archived": False}

        pi = HarnessPlugin("pi-agent")
        claude = HarnessPlugin("claude-agent")
        pi.release.set()
        claude.release.set()
        registry = PluginRegistry()
        registry.register("codex-app-server", HarnessPlugin("codex-agent"), "codex")
        registry.register("pi", pi, "pi")
        registry.register("claude-sdk", claude, "claude")
        supervisor = Supervisor(tmp_path, registry)

        assert await supervisor.send("pi-agent", "pi prompt") == SendOutcome.SENT
        assert (
            await supervisor.send("claude-agent", "claude prompt") == SendOutcome.SENT
        )
        assert pi.sent == ["pi prompt"]
        assert claude.sent == ["claude prompt"]
        await supervisor.shutdown()

    asyncio.run(run())


def test_session_lookup_guards_malformed_refs_and_matches_harness(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        plugin = FakePlugin()
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        first = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        second = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        supervisor.store.update_session(
            first.session_id, harness="harness-a", agent_id="shared"
        )
        supervisor.store.update_session(
            second.session_id, harness="harness-b", agent_id="shared"
        )
        matched = supervisor._session_row("shared", "harness-b")
        assert matched is not None and matched["id"] == second.session_id
        supervisor.store.connection.execute(
            "UPDATE sessions SET ref = ? WHERE id = ?", ("{", first.session_id)
        )
        supervisor.store.connection.commit()
        assert supervisor._session_row("missing", "harness-a") is None
        await supervisor.shutdown()

    asyncio.run(run())


def test_ipc_respond_routes_once_and_fails_stale_requests_closed(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        plugin = FakePlugin()
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        session = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        await supervisor.record_event(
            session.session_id,
            "permission_requested",
            {"request_id": "request-1"},
        )
        assert await supervisor._handle_ipc(
            {
                "op": "respond",
                "session_id": session.session_id,
                "request_id": "request-1",
                "decision": "deny",
            }
        ) == {"outcome": "responded"}
        assert (
            await supervisor.respond(session.session_id, "request-1", "deny")
            == "responded"
        )
        assert (
            await supervisor.respond(session.session_id, "unknown", "deny") == "stale"
        )
        assert plugin.responses == [("request-1", "deny")]
        await supervisor.shutdown()

    asyncio.run(run())


def test_respond_fails_unsupported_and_plugin_errors_closed(tmp_path: Path) -> None:
    async def run() -> None:
        unsupported = FakePlugin()
        unsupported.capabilities = RunnerCapabilities()
        first = Supervisor(tmp_path / "unsupported", {"fake": unsupported})
        session = await first.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        assert await first.respond(session.session_id, "req", "deny") == "unsupported"
        await first.shutdown()

        failing = FakePlugin()
        failing.respond_fails = True
        second = Supervisor(tmp_path / "failing", {"fake": failing})
        session = await second.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        await second.record_event(
            session.session_id, "permission_requested", {"request_id": "req"}
        )
        assert await second.respond(session.session_id, "req", "deny") == "failed"
        assert failing.responses == []
        await second.shutdown()

    asyncio.run(run())


def test_respond_is_independent_of_parked_send_and_persists_idempotency(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        plugin = FakePlugin()
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        session = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        await supervisor.record_event(session.session_id, "status", {"status": "idle"})
        await supervisor.record_event(
            session.session_id, "permission_requested", {"request_id": "req"}
        )
        sending = asyncio.create_task(supervisor.send(session.session_id, "turn"))
        await plugin.entered.wait()
        assert (
            await asyncio.wait_for(
                supervisor.respond(session.session_id, "req", "deny"), timeout=0.2
            )
            == "responded"
        )
        plugin.release.set()
        assert await sending == SendOutcome.SENT
        await supervisor.shutdown()

        restarted = Supervisor(tmp_path, {"fake": plugin})
        await restarted.start()
        assert await restarted.respond(session.session_id, "req", "deny") == "responded"
        assert await restarted.respond(session.session_id, "req", "approve") == "stale"
        assert plugin.responses == [("req", "deny")]
        await restarted.shutdown()

    asyncio.run(run())


def test_ipc_socket_send_returns_documented_outcome(
    tmp_path: Path, require_unix_socket
) -> None:
    async def run() -> None:
        plugin = FakePlugin()
        plugin.release.set()
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        session = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        await supervisor.record_event(session.session_id, "status", {"status": "idle"})
        path = Path(tempfile.gettempdir()) / f"varde-{uuid.uuid4().hex[:8]}.sock"
        await supervisor.start_ipc(path)
        reader, writer = await asyncio.open_unix_connection(path)
        writer.write(
            (
                json.dumps(
                    {"op": "send", "session_id": session.session_id, "prompt": "ipc"}
                )
                + "\n"
            ).encode()
        )
        await writer.drain()
        response = json.loads(await reader.readline())
        assert response == {"outcome": "sent"}
        writer.close()
        await writer.wait_closed()
        await supervisor.shutdown()

    asyncio.run(run())


def test_app_relay_lifespan_uses_the_started_supervisor(
    tmp_path: Path, monkeypatch
) -> None:
    async def run() -> None:
        plugin = FakePlugin()
        monkeypatch.setattr(
            "varde_runner.web.registry.PaseoPlugin.from_environment", lambda: plugin
        )
        monkeypatch.setenv("VARDE_RUNNER_RELAY", "1")

        async def no_relay_io(self):
            return None

        monkeypatch.setattr("varde_runner.relay.RelayWorker.run", no_relay_io)
        app = create_app(data_dir=tmp_path)
        async with app.router.lifespan_context(app):
            worker = app.state.relay_worker
            assert isinstance(worker.supervisor, Supervisor)
            assert worker.supervisor is app.state.supervisor

    asyncio.run(run())
