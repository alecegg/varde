from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest
from varde_runner import agent_launch
from varde_runner.config import KNOWN_HARNESSES, default_toml
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSettings
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.protocol import RunnerPlugin
from varde_runner.supervisor import Supervisor


class FakePlugin:
    capabilities = RunnerCapabilities()

    def __init__(self, workspace: Path | None = None):
        self.spec = None
        self.workspace = workspace
        self.fail_start = False
        self.stopped = []

    def session_settings(self, model):
        return SessionSettings(model.model, model.reasoning_effort, model.mode)

    async def list_workspaces(self):
        if self.workspace is None:
            return []
        return [{"id": "listed-id", "cwd": str(self.workspace)}]

    async def start(self, spec):
        self.spec = spec
        if self.fail_start:
            raise RuntimeError("start failed")
        return SessionRef(spec.provider, "remote-id")

    async def stop(self, ref):
        self.stopped.append(ref.session_id)

    async def events(self, ref):
        await asyncio.Event().wait()
        yield

    async def close(self):
        return None


def setup(tmp_path: Path, monkeypatch, workspace: Path | None = None):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "runner.toml").write_text(default_toml(), encoding="utf-8")
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))
    plugin = FakePlugin(workspace)
    registry = PluginRegistry((*KNOWN_HARNESSES, "disabled"))
    registry.register("claude-sdk", cast("RunnerPlugin", plugin))
    registry.register("codex-app-server", cast("RunnerPlugin", plugin))
    registry.register("pi", cast("RunnerPlugin", plugin))
    supervisor = Supervisor(tmp_path / "data", registry)
    return supervisor, plugin


def test_launch_reads_real_toml_and_preserves_prompt(tmp_path, monkeypatch):
    supervisor, plugin = setup(tmp_path, monkeypatch)
    prompt = "  exact\n prompt  "

    ref = asyncio.run(
        agent_launch.launch_agent(
            supervisor, "codex-app-server", str(tmp_path), "builder", prompt
        )
    )

    assert ref.provider == "codex-app-server"
    assert plugin.spec is not None
    assert plugin.spec.model == "gpt-6-luna"
    assert plugin.spec.reasoning_effort == "medium"
    assert plugin.spec.mode_id == "workspace-write"
    assert plugin.spec.prompt == prompt


@pytest.mark.parametrize(
    ("harness", "workspace", "role", "error"),
    [
        ("codex-app-server", ".", "missing", agent_launch.AgentLaunchError),
        ("disabled", ".", "builder", agent_launch.DisabledHarnessError),
        (
            "codex-app-server",
            "missing-directory",
            "builder",
            agent_launch.AgentLaunchError,
        ),
        ("unknown", ".", "builder", agent_launch.AgentLaunchError),
        ("pi", ".", "builder", agent_launch.AgentLaunchError),
    ],
)
def test_launch_rejects_invalid_selection(
    tmp_path, monkeypatch, harness, workspace, role, error
):
    supervisor, _ = setup(tmp_path, monkeypatch)
    with pytest.raises(error):
        asyncio.run(
            agent_launch.launch_agent(supervisor, harness, workspace, role, "prompt")
        )


def test_launch_accepts_listed_workspace_id(tmp_path, monkeypatch):
    supervisor, plugin = setup(tmp_path, monkeypatch, tmp_path)
    asyncio.run(
        agent_launch.launch_agent(
            supervisor, "codex-app-server", "listed-id", "builder", "prompt"
        )
    )
    assert plugin.spec is not None
    assert plugin.spec.workspace_id == "listed-id"
    assert plugin.spec.cwd == str(tmp_path.resolve())


def test_address_start_failure_revokes_issued_marker(tmp_path, monkeypatch):
    supervisor, plugin = setup(tmp_path, monkeypatch)
    plugin.fail_start = True
    revoked = []
    monkeypatch.setattr(agent_launch, "_issue_address", lambda *_: ("marker", False))

    def fail_revoke(*_args):
        revoked.append(True)
        raise RuntimeError("revoke failed")

    monkeypatch.setattr(agent_launch, "_revoke_address", fail_revoke)
    with pytest.raises(RuntimeError, match="start failed"):
        asyncio.run(
            agent_launch.launch_agent(
                supervisor,
                "codex-app-server",
                str(tmp_path),
                "builder",
                "prompt",
                {"slot": "builder-slot", "plan": None},
            )
        )
    assert revoked == [True]


def test_address_bind_failure_stops_session_and_revokes_marker(tmp_path, monkeypatch):
    supervisor, plugin = setup(tmp_path, monkeypatch)
    revoked = []
    monkeypatch.setattr(agent_launch, "_issue_address", lambda *_: ("marker", False))

    monkeypatch.setattr(
        agent_launch,
        "_binding_details",
        lambda *_: ("remote-id", "codex", None),
    )
    monkeypatch.setattr(agent_launch, "_redeem_address", lambda *_: False)
    monkeypatch.setattr(
        agent_launch, "_revoke_address", lambda *_: revoked.append(True)
    )
    with pytest.raises(agent_launch.AgentLaunchError, match="could not bind"):
        asyncio.run(
            agent_launch.launch_agent(
                supervisor,
                "codex-app-server",
                str(tmp_path),
                "builder",
                "prompt",
                {"slot": "builder-slot", "plan": None},
            )
        )
    assert plugin.stopped == ["remote-id"]
    assert revoked == [True]


def test_address_is_revoked_even_when_stop_fails(tmp_path, monkeypatch):
    supervisor, _ = setup(tmp_path, monkeypatch)
    revoked = []
    monkeypatch.setattr(agent_launch, "_issue_address", lambda *_: ("marker", False))
    monkeypatch.setattr(
        agent_launch, "_binding_details", lambda *_: ("remote-id", "codex", None)
    )
    monkeypatch.setattr(agent_launch, "_redeem_address", lambda *_: False)
    monkeypatch.setattr(
        agent_launch, "_revoke_address", lambda *_: revoked.append(True)
    )

    async def fail_stop(*_args):
        raise RuntimeError("stop failed")

    monkeypatch.setattr(supervisor, "stop", fail_stop)
    with pytest.raises(agent_launch.AgentLaunchError, match="could not bind"):
        asyncio.run(
            agent_launch.launch_agent(
                supervisor,
                "codex-app-server",
                str(tmp_path),
                "builder",
                "prompt",
                {"slot": "builder-slot", "plan": None},
            )
        )
    assert revoked == [True]


@pytest.mark.parametrize(
    "harness", ["claude-cli", "codex-app-server", "pi", "opencode-http"]
)
def test_planner_harness_matches_agent_launch_name(harness):
    assert agent_launch.runner_harness_name(harness) == harness


def test_address_binding_survives_supervisor_restart(tmp_path, monkeypatch):
    from types import SimpleNamespace

    supervisor, _ = setup(tmp_path, monkeypatch)
    supervisor.store.create_session(
        "agent", "codex", {"session_id": "remote"}, "builder"
    )
    supervisor.register_address_binding("agent", tmp_path, "remote")
    second = Supervisor(tmp_path / "data", supervisor.registry)
    unbound = []

    class Addresses:
        def unbind(self, remote_id, _now):
            unbound.append(remote_id)

    monkeypatch.setattr(
        "varde_data.open.open_data",
        lambda *_: SimpleNamespace(addresses=Addresses()),
    )
    second._unbind_address_binding("agent")
    assert unbound == ["remote"]


def test_revoke_preserves_preexisting_plan_alias(tmp_path, monkeypatch):
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.service import AddressService

    monkeypatch.delenv("VARDE_WORKING_DIR", raising=False)
    data = open_data(tmp_path, load_data_config())
    AddressService(data.addresses, data.messages).add_alias("slot", "existing-plan")
    marker, alias_created = agent_launch._issue_address(
        tmp_path, {"slot": "slot", "plan": "existing-plan"}
    )
    assert marker
    assert alias_created is False

    agent_launch._revoke_address(
        tmp_path, {"slot": "slot", "plan": "existing-plan"}, alias_created
    )

    assert any("existing-plan" in slot.aliases for slot in data.addresses.slots())


def test_launch_without_harness_uses_the_role_harness(tmp_path, monkeypatch):
    supervisor, plugin = setup(tmp_path, monkeypatch)
    ref = asyncio.run(
        agent_launch.launch_agent(supervisor, None, str(tmp_path), "builder", "go")
    )
    assert ref.provider == "codex-app-server"
    assert plugin.spec is not None


def test_launch_mode_overrides_the_role_mode(tmp_path, monkeypatch):
    supervisor, plugin = setup(tmp_path, monkeypatch)
    asyncio.run(
        agent_launch.launch_agent(
            supervisor, None, str(tmp_path), "builder", "go", mode="full-access"
        )
    )
    assert plugin.spec is not None
    assert plugin.spec.mode_id == "full-access"


def test_launch_rejected_mode_is_a_launch_error(tmp_path, monkeypatch):
    supervisor, plugin = setup(tmp_path, monkeypatch)
    plugin.fail_start = True
    with pytest.raises(agent_launch.AgentLaunchError, match="bogus"):
        asyncio.run(
            agent_launch.launch_agent(
                supervisor, None, str(tmp_path), "builder", "go", mode="bogus"
            )
        )


def test_launch_stores_parent_id_on_the_session(tmp_path, monkeypatch):
    supervisor, _ = setup(tmp_path, monkeypatch)
    ref = asyncio.run(
        agent_launch.launch_agent(
            supervisor, None, str(tmp_path), "builder", "go", parent_id="parent-1"
        )
    )
    row = supervisor.store.get_session(ref.session_id)
    assert row is not None
    assert row["parent_id"] == "parent-1"
    other = asyncio.run(
        agent_launch.launch_agent(supervisor, None, str(tmp_path), "builder", "go")
    )
    other_row = supervisor.store.get_session(other.session_id)
    assert other_row is not None
    assert other_row["parent_id"] is None


def test_binding_context_carries_the_parent_id(tmp_path, monkeypatch):
    supervisor, _ = setup(tmp_path, monkeypatch)
    ref = asyncio.run(
        agent_launch.launch_agent(supervisor, None, str(tmp_path), "builder", "go")
    )
    _, _, context = agent_launch._binding_details(
        supervisor, ref, tmp_path, "codex-app-server", "parent-1"
    )
    assert context.parent_id == "parent-1"


def test_launch_stores_launched_by_on_the_session(tmp_path, monkeypatch):
    supervisor, _ = setup(tmp_path, monkeypatch)
    ref = asyncio.run(
        agent_launch.launch_agent(
            supervisor, None, str(tmp_path), "builder", "go", launched_by="bot:manager"
        )
    )
    row = supervisor.store.get_session(ref.session_id)
    assert row is not None
    assert row["launched_by"] == "bot:manager"
    other = asyncio.run(
        agent_launch.launch_agent(supervisor, None, str(tmp_path), "builder", "go")
    )
    other_row = supervisor.store.get_session(other.session_id)
    assert other_row is not None and other_row["launched_by"] is None
