from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from fakes.plugin import FakePlugin
from varde_runner.config import default_config
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.protocol import ResumeSettings, UnsupportedCapability
from varde_runner.supervisor import Supervisor

CLIENT = "system:dashboard"


class NoSettingsPlugin(FakePlugin):
    async def resume(self, ref: SessionRef) -> SessionRef:  # type: ignore[override]
        return await super().resume(ref)


def build(tmp_path, monkeypatch, plugin: FakePlugin):
    config = replace(default_config(), stall_after_s=10)
    monkeypatch.setattr("varde_runner.supervisor.load_config", lambda *_: config)
    registry = PluginRegistry(["claude_cli"])
    registry.register("claude_cli", plugin)
    supervisor = Supervisor(tmp_path, registry)
    asyncio.run(supervisor.start())
    ref = asyncio.run(
        supervisor.start_session(
            SessionSpec("claude_cli", "m", "w", str(tmp_path), "hi"), "builder"
        )
    )
    return supervisor, ref


def test_set_mode_stops_then_resumes_with_the_new_mode(tmp_path, monkeypatch) -> None:
    plugin = FakePlugin(RunnerCapabilities(resume=True, idle_status=True))
    supervisor, ref = build(tmp_path, monkeypatch, plugin)

    asyncio.run(supervisor.set_mode(ref.session_id, CLIENT, "full-access"))

    assert plugin.stopped == ["remote-1"]
    assert plugin.resumed_settings == [ResumeSettings(mode_id="full-access")]
    row = supervisor.store.get_session(ref.session_id)
    assert row is not None
    assert row["mode"] == "full-access"
    assert row["lifecycle"] != "completed"


def test_set_mode_rejects_an_invalid_mode_before_stopping(
    tmp_path, monkeypatch
) -> None:
    plugin = FakePlugin(RunnerCapabilities(resume=True, idle_status=True))
    supervisor, ref = build(tmp_path, monkeypatch, plugin)

    with pytest.raises(ValueError, match="bogus"):
        asyncio.run(supervisor.set_mode(ref.session_id, CLIENT, "bogus"))

    assert plugin.stopped == []


def test_set_mode_refuses_plugins_that_cannot_change_settings(
    tmp_path, monkeypatch
) -> None:
    plugin = NoSettingsPlugin(RunnerCapabilities(resume=True, idle_status=True))
    supervisor, ref = build(tmp_path, monkeypatch, plugin)

    with pytest.raises(UnsupportedCapability, match="mode change"):
        asyncio.run(supervisor.set_mode(ref.session_id, CLIENT, "auto"))

    assert plugin.stopped == []


def test_set_mode_requires_resume_capability(tmp_path, monkeypatch) -> None:
    plugin = FakePlugin(RunnerCapabilities(resume=False))
    supervisor, ref = build(tmp_path, monkeypatch, plugin)

    with pytest.raises(UnsupportedCapability):
        asyncio.run(supervisor.set_mode(ref.session_id, CLIENT, "auto"))

    assert plugin.stopped == []


def test_set_mode_unknown_agent_raises_key_error(tmp_path, monkeypatch) -> None:
    plugin = FakePlugin()
    supervisor, _ = build(tmp_path, monkeypatch, plugin)
    with pytest.raises(KeyError):
        asyncio.run(supervisor.set_mode("missing", CLIENT, "auto"))


def test_protocol_resume_passes_settings_only_when_given() -> None:
    from varde_runner.protocol import resume

    plugin = FakePlugin(RunnerCapabilities(resume=True))
    ref = SessionRef("p", "r1")
    asyncio.run(resume(plugin, ref))
    asyncio.run(resume(plugin, ref, ResumeSettings(mode_id="auto")))
    assert plugin.resumed_settings == [None, ResumeSettings(mode_id="auto")]
    legacy = NoSettingsPlugin(RunnerCapabilities(resume=True))
    asyncio.run(resume(legacy, ref))
    with pytest.raises(UnsupportedCapability):
        asyncio.run(resume(legacy, ref, ResumeSettings(mode_id="auto")))
