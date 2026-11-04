from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any, cast

from fakes.plugin import FakePlugin
from test_web import app_request
from varde_runner.config import default_toml
from varde_runner.delivery import DeliveryLoop
from varde_runner.plugins import RunnerCapabilities, SessionSpec
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.registry import SessionBinding, SessionRegistry
from varde_runner.relay import RelayCLIProtocol, RelayWorker
from varde_runner.supervisor import SendOutcome, Supervisor
from varde_runner.web import create_app
from varde_runner.web import registry as web_registry


def test_second_plugin_runs_management_flows_end_to_end(tmp_path, monkeypatch):
    async def run():
        plugin = FakePlugin()
        registry = PluginRegistry()
        for harness in ("claude-sdk", "codex-app-server", "pi"):
            registry.register(harness, plugin, provider_key="fake-provider")
        supervisor = Supervisor(tmp_path / "sessions", registry)

        monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
        (tmp_path / "runner.toml").write_text(default_toml(), encoding="utf-8")
        planner = await supervisor.start_planner_session(
            "plan-123", tmp_path, "workspace"
        )
        assert planner.provider == "fake-provider"
        assert len(plugin.started) == 1

        await supervisor.record_event(
            planner.session_id,
            "permission_requested",
            {"request_id": "permission-1", "kind": "command"},
        )
        await supervisor.record_event(
            planner.session_id,
            "tool_intent",
            {
                "call_id": "neutral-call",
                "tool": "shell",
                "phase": "running",
                "raw": {"command": "pwd"},
            },
        )
        neutral_events = supervisor.store.events_after(planner.session_id, 0)
        assert any(
            event["kind"] == "tool_intent"
            and event["payload"]["call_id"] == "neutral-call"
            for event in neutral_events
        )
        assert (
            await supervisor.respond(planner.session_id, "permission-1", "deny")
            == "responded"
        )
        assert plugin.responses == [("permission-1", "deny")]

        binding = SessionBinding(
            "planner", "claude-sdk", "fake-provider", "remote-1", "planner"
        )
        sessions = SessionRegistry(tmp_path / "addresses.json")
        sessions.register(binding)
        delivery = DeliveryLoop(
            tmp_path / "delivery.jsonl",
            sessions,
            supervisor,
            lambda: [{"id": "message-1", "to": "planner", "text": "deliver"}],
        )
        assert await delivery.deliver_once() == 1
        assert plugin.sent == [("remote-1", "deliver")]

        class RelayCommand:
            async def renew(self, action_id):
                return {"status": "active"}

        worker = RelayWorker(
            cast("RelayCLIProtocol", cast("Any", RelayCommand())), supervisor
        )
        plugin.status["remote-1"] = "idle"
        assert await worker.deliver(
            {
                "action_id": "wake-1",
                "wake": {"harness": "claude-sdk", "agent_id": "remote-1"},
                "prompt": "wake",
            }
        ) == ("pushed", "successful-send")
        assert plugin.sent[-1] == ("remote-1", "wake")

        await supervisor.shutdown()
        return registry

    registry = asyncio.run(asyncio.wait_for(run(), timeout=5))
    monkeypatch.setattr(web_registry, "build_registry", lambda: registry)
    app = create_app(data_dir=tmp_path / "dashboard")
    app.state.registry = registry
    capabilities = app_request(app, "GET", "/api/agents/capabilities").json()
    assert capabilities["claude-sdk"]["respond"] is True
    assert capabilities["claude-sdk"]["interrupt"] is True


def test_resume_capability_controls_restart_recovery(tmp_path):
    async def run():
        capable = FakePlugin()
        first = Supervisor(tmp_path / "resumable", {"fake-harness": capable})
        session = await first.start_session(
            SessionSpec("fake-harness", "model", "workspace", str(tmp_path)),
            "builder",
        )
        await first.shutdown()
        resumed = Supervisor(tmp_path / "resumable", {"fake-harness": capable})
        await resumed.start()
        assert capable.resumed == ["remote-1"]
        resumed_row = resumed.store.get_session(session.session_id)
        assert resumed_row is not None
        assert resumed_row["status"] == "running"
        await resumed.shutdown()

        limited = FakePlugin(RunnerCapabilities(idle_status=True))
        original = Supervisor(tmp_path / "nonresumable", {"fake-harness": limited})
        other = await original.start_session(
            SessionSpec("fake-harness", "model", "workspace", str(tmp_path)),
            "builder",
        )
        await original.shutdown()
        restarted = Supervisor(tmp_path / "nonresumable", {"fake-harness": limited})
        await restarted.start()
        restarted_row = restarted.store.get_session(other.session_id)
        assert restarted_row is not None
        assert restarted_row["status"] == "error"
        assert limited.resumed == []
        await restarted.shutdown()

    asyncio.run(asyncio.wait_for(run(), timeout=5))


def test_interrupt_timeout_and_concurrent_senders_are_bounded(tmp_path):
    async def run():
        plugin = FakePlugin()
        supervisor = Supervisor(tmp_path, {"fake-harness": plugin})
        session = await supervisor.start_session(
            SessionSpec("fake-harness", "model", "workspace", str(tmp_path)),
            "builder",
        )
        plugin.interrupt_sets_idle = False
        plugin.status["remote-1"] = "running"
        supervisor.interrupt_timeout = 0.03
        assert await supervisor.send_with_interrupt(session.session_id, "blocked") == (
            SendOutcome.FAILED_INTERRUPT
        )
        assert plugin.sent == []

        plugin.interrupt_sets_idle = True
        plugin.status["remote-1"] = "idle"
        plugin._send_started = asyncio.Event()
        plugin._release_send = asyncio.Event()
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
        key = target[3]
        supervisor._send_locks[key] = cast("asyncio.Lock", ObservedLock())
        first = asyncio.create_task(supervisor.send(session.session_id, "first"))
        await plugin._send_started.wait()
        second = asyncio.create_task(supervisor.send(session.session_id, "second"))
        await waiting.wait()
        assert len(plugin.sent) == 0
        plugin._release_send.set()
        assert await first == SendOutcome.SENT
        assert await second == SendOutcome.SKIPPED_BUSY
        assert plugin.sent == [("remote-1", "first")]
        await supervisor.shutdown()

    asyncio.run(asyncio.wait_for(run(), timeout=3))


def test_runner_source_keeps_harness_names_in_adapter_and_registry_modules():
    source_root = Path(__file__).parents[1] / "src" / "varde_runner"
    allowed = {
        Path("harness_map.py"): "Maps legacy Paseo settings into provider settings.",
        Path("config.py"): (
            "Defines supported harnesses and validates legacy Paseo policy."
        ),
        Path("generate.py"): "Maps configured harnesses to provider identifiers.",
        Path("relay.py"): "Uses Codex identities for core relay bindings and receipts.",
        Path("relay_cli.py"): "Passes the Codex harness to core address binding.",
        Path("web/activity.py"): "Reads legacy Paseo parent-agent labels.",
        Path("wake.py"): "Reads the legacy paseo_id wake binding.",
        Path("web/app.py"): (
            "Maps dashboard providers and preserves legacy paseo_id fields."
        ),
        Path("gate_check.py"): (
            "Inspects stored runner sessions and Paseo residue after restart."
        ),
        Path("bot_wake.py"): "Reads the legacy paseo_id wake binding.",
        Path("agent_launch.py"): "Maps configured harnesses to launch providers.",
        Path("plugins/__init__.py"): (
            "Removes ambient Paseo identity from native child environments."
        ),
        Path("web/runner_config_sdk_flip.py"): (
            "Migrates legacy SDK role settings during the config flip."
        ),
        Path("service/__init__.py"): "Maps runner providers for service launch.",
    }
    harness_names = {
        "claude-sdk",
        "claude-cli",
        "codex-app-server",
        "pi-rpc",
        "opencode-http",
    }
    provider_names = {"pi", "codex", "claude"}
    violations = []
    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root)
        is_harness_adapter = relative.parts[0] == "plugins" and (
            relative in {Path("plugins/paseo.py"), Path("plugins/registry.py")}
            or any(
                part
                in {
                    "pi_rpc",
                    "opencode_http",
                    "codex_app_server",
                    "claude_cli",
                    "claude_sdk",
                }
                for part in relative.parts
            )
        )
        if is_harness_adapter or relative == Path("web/registry.py"):
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            if "paseo" in line.casefold() and relative not in allowed:
                violations.append(f"{path}:{number}: {line.strip()}")

        tree = ast.parse("\n".join(lines), filename=str(path))
        provider_literal_nodes = set()
        for parent in ast.walk(tree):
            if isinstance(parent, (ast.Set, ast.Tuple, ast.List)):
                provider_literal_nodes.update(
                    id(node)
                    for node in ast.walk(parent)
                    if isinstance(node, ast.Constant) and node.value in provider_names
                )
            elif isinstance(parent, ast.Dict):
                provider_literal_nodes.update(
                    id(node)
                    for key in parent.keys
                    if key is not None
                    for node in ast.walk(key)
                    if isinstance(node, ast.Constant) and node.value in provider_names
                )
            elif isinstance(parent, ast.MatchValue):
                if (
                    isinstance(parent.value, ast.Constant)
                    and parent.value.value in provider_names
                ):
                    provider_literal_nodes.add(id(parent.value))
            elif isinstance(parent, ast.Compare) and any(
                isinstance(operator, ast.In) for operator in parent.ops
            ):
                provider_literal_nodes.update(
                    id(node)
                    for comparator in parent.comparators
                    for node in ast.walk(comparator)
                    if isinstance(node, ast.Constant) and node.value in provider_names
                )
        provider_comparison_constants = {
            id(value)
            for comparison in ast.walk(tree)
            if isinstance(comparison, ast.Compare)
            for value in (comparison.left, *comparison.comparators)
            if isinstance(value, ast.Constant) and value.value in provider_names
        }
        provider_comparison_constants.update(provider_literal_nodes)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value.casefold()
            is_harness_name = value in harness_names
            is_provider_comparison = id(node) in provider_comparison_constants
            if (is_harness_name or is_provider_comparison) and relative not in allowed:
                violations.append(f"{path}:{node.lineno}: {node.value!r}")
    assert not violations, "Harness-specific code outside allow-list:\n" + "\n".join(
        violations
    )
