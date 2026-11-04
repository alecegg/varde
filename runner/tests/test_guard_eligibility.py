import asyncio
from dataclasses import replace

import pytest
from varde_runner.config import ConfigError, default_config
from varde_runner.events import RunnerEvent
from varde_runner.guard_policy import validate_guard_role
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.plugins.codex_app_server import wire
from varde_runner.plugins.codex_app_server.plugin import CodexAppServerPlugin
from varde_runner.plugins.registry import PluginRegistry


class FakePlugin:
    def __init__(self, guard_read_only: bool):
        self.capabilities = RunnerCapabilities(guard_read_only=guard_read_only)


def test_guard_requires_verified_read_only_capability():
    role = replace(default_config().roles["guard"], enabled=True)
    registry = PluginRegistry()
    registry.register("codex-app-server", FakePlugin(True))  # type: ignore[arg-type]
    validate_guard_role(role, registry)

    registry.register("claude-cli", FakePlugin(False))  # type: ignore[arg-type]
    with pytest.raises(
        ConfigError,
        match="guard role harness claude-cli is not verified read-only",
    ):
        validate_guard_role(replace(role, harness="claude-cli"), registry)


def test_only_codex_plugin_claims_verified_read_only_capability():
    assert CodexAppServerPlugin.capabilities.guard_read_only is True
    assert RunnerCapabilities().guard_read_only is False


def test_codex_guard_process_is_launched_with_read_only_sandbox():
    command = wire.build_command("read-only")
    assert 'sandbox_mode="read-only"' in command
    assert 'approval_policy="never"' in command


def test_codex_guard_turn_discards_ephemeral_session_state(tmp_path, monkeypatch):
    plugin = CodexAppServerPlugin(executable="codex", state_dir=tmp_path)
    ref = SessionRef("codex-app-server", "guard-session")
    removed = []
    cleared = []

    async def start(spec):
        assert spec.mode_id == "read-only"
        return ref

    async def events(_ref):
        yield RunnerEvent("text", ref.session_id, {"text": "verdict"})
        yield RunnerEvent("session_end", ref.session_id, {"status": "completed"})

    async def stop(_ref):
        return None

    monkeypatch.setattr(plugin, "start", start)
    monkeypatch.setattr(plugin, "events", events)
    monkeypatch.setattr(plugin, "stop", stop)
    monkeypatch.setattr(plugin, "_remove_spec", removed.append)
    monkeypatch.setattr(plugin, "_clear_live_state", cleared.append)
    spec = SessionSpec(
        provider="codex-app-server",
        model="gpt-6-luna",
        workspace_id="guard",
        cwd=str(tmp_path),
        prompt="prompt",
        mode_id="read-only",
    )

    assert asyncio.run(plugin.run_guard(spec)) == "verdict"
    assert removed == [ref.session_id]
    assert cleared == [ref.session_id]
