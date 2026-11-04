from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from varde_runner.config import ConfigError, default_toml, parse_config
from varde_runner.plugins import SessionSpec
from varde_runner.plugins.claude_cli.plugin import ClaudeCliPlugin, ProcessIdentity
from varde_runner.supervisor import Supervisor
from varde_runner.waits import approval_wait_id
from varde_runner.web.registry import build_registry

FAKE = Path(__file__).parent / "fakes" / "fake_claude.py"


def test_claude_cli_is_absent_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    registry = build_registry()
    assert "claude-cli" not in registry.harnesses()


def test_claude_cli_requires_explicit_enablement():
    config = default_toml().replace(
        '[types.light]\nharness = "codex-app-server"',
        '[types.light]\nharness = "claude-cli"',
    )
    with pytest.raises(ConfigError, match=r"claude_cli.*enabled = true"):
        parse_config(config, {"codex-app-server", "pi", "claude-sdk", "claude-cli"})


def test_enabled_claude_cli_can_be_selected_by_a_role():
    config = (
        default_toml()
        .replace("enabled = false", "enabled = true")
        .replace(
            '[roles.orchestrator]\ntype = "standard"',
            '[roles.orchestrator]\ntype = "cli-planner"',
        )
        + """
[types.cli-planner]
harness = "claude-cli"
model = "claude-sonnet-5-5"
reasoning_effort = "medium"

[[types.cli-planner.fallback]]
harness = "pi"
model = "deepseek/deepseek-v4-flash"
reasoning_effort = "high"
"""
    )
    assert (
        parse_config(config, {"codex-app-server", "pi", "claude-sdk", "claude-cli"})
        .resolve("orchestrator")
        .harness
        == "claude-cli"
    )


def test_claude_cli_registers_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "runner.toml").write_text(
        default_toml().replace("enabled = false", "enabled = true"), encoding="utf-8"
    )
    registry = build_registry()
    assert "claude-cli" in registry.harnesses()
    assert "claude-sdk" in registry.harnesses()


def test_permission_input_is_redacted_before_store_and_becomes_decision_card(tmp_path):
    async def exercise():
        plugin = ClaudeCliPlugin(
            FAKE,
            state_dir=tmp_path / "state",
            process_inspector=lambda _pid, command: ProcessIdentity(
                "test-start", " ".join(command)
            ),
        )
        supervisor = Supervisor(tmp_path / "sessions", {"claude-cli": plugin})
        ref = await supervisor.start_session(
            SessionSpec("claude-cli", "model", "agent", str(tmp_path)), "builder"
        )
        try:
            permission = None
            for _ in range(100):
                rows = supervisor.store.events_after(ref.session_id, 0)
                permission = next(
                    (row for row in rows if row["kind"] == "permission_requested"), None
                )
                if permission:
                    break
                await asyncio.sleep(0.01)
            assert permission is not None
            assert "input" not in permission["payload"]
            assert "private-input" not in str(permission["payload"])
            assert supervisor.store.has_decision_event(
                approval_wait_id(ref.session_id, "permit-1")
            )
            assert (
                await supervisor.respond(ref.session_id, "permit-1", "deny")
                == "responded"
            )
        finally:
            await supervisor.shutdown()

    asyncio.run(exercise())


def test_supervisor_sweeps_mismatched_orphan_before_resume(tmp_path, monkeypatch):
    async def exercise():
        monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path / "config"))
        session_id = str(uuid.uuid4())
        signals = []
        plugin = ClaudeCliPlugin(
            FAKE,
            state_dir=tmp_path / "claude-state",
            process_inspector=lambda pid, command: ProcessIdentity(
                "reused-pid-start", " ".join(command)
            ),
            process_group_exists=lambda _group: True,
            process_group_signal=lambda *args: signals.append(args),
        )
        plugin._persist_spec(
            session_id, SessionSpec("claude-cli", "model", "agent", str(tmp_path))
        )
        state_path = plugin._spec_path(session_id)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state.update(
            pid=4321,
            process_group=4321,
            command=[str(FAKE), "--session-id", session_id],
            started_at="old-process-start",
        )
        state_path.write_text(json.dumps(state), encoding="utf-8")

        supervisor = Supervisor(tmp_path / "sessions", {"claude-cli": plugin})
        supervisor.store.create_session(
            "stored-session",
            "claude-cli",
            {"provider": "claude-cli", "session_id": session_id},
            "builder",
        )
        await supervisor.start()
        try:
            stored_session = supervisor.store.get_session("stored-session")
            assert stored_session is not None
            assert stored_session["status"] == "error"
            assert signals == []
            assert (
                json.loads(state_path.read_text())["recovery_status"] == "unavailable"
            )
        finally:
            await supervisor.shutdown()

    asyncio.run(exercise())
