# ruff: noqa: S105 - fake secret values prove they stay with the right sessions.
from __future__ import annotations

import ast
from pathlib import Path

from varde_runner.plugins import SessionSpec, child_environment
from varde_runner.plugins.codex_app_server.plugin import child_env as codex_child_env


def test_child_environment_removes_ambient_identity_but_keeps_auth_and_config(
    monkeypatch,
):
    monkeypatch.setenv("PASEO_AGENT_ID", "parent-agent")
    monkeypatch.setenv("PASEO_WORKSPACE_ID", "parent-workspace")
    monkeypatch.setenv("VARDE_ADDRESS", "wrong-address")
    monkeypatch.setenv("VARDE_RUNNER_ENDPOINT", "parent-endpoint")
    monkeypatch.setenv("VARDE_DATA_ADDRESSES_BACKEND", "files")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "provider-key")

    env = child_environment()

    assert not any(key.startswith("PASEO_") for key in env)
    assert "VARDE_ADDRESS" not in env
    assert "VARDE_RUNNER_ENDPOINT" not in env
    assert env["VARDE_DATA_ADDRESSES_BACKEND"] == "files"
    assert env["ANTHROPIC_API_KEY"] == "provider-key"


def test_all_native_plugins_use_scrubbed_child_environment():
    root = Path(__file__).parents[1] / "src" / "varde_runner" / "plugins"
    for plugin in ("claude_cli", "codex_app_server", "pi_rpc", "opencode_http"):
        source = (root / plugin / "plugin.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "child_environment" in calls, plugin


def test_codex_child_environment_uses_runner_agent_id(monkeypatch, tmp_path):
    monkeypatch.setenv("VARDE_AGENT_ID", "ambient-agent")
    spec = SessionSpec(
        "codex-app-server",
        "model",
        str(tmp_path),
        str(tmp_path),
        agent_id="runner-agent",
    )

    env = codex_child_env(spec)

    assert env["VARDE_AGENT_ID"] == "runner-agent"
    assert env["VARDE_HARNESS"] == "codex-app-server"


def test_normal_launch_keeps_its_full_environment_plus_the_overlay(
    monkeypatch, tmp_path
):
    from varde_runner.plugins.claude_cli.plugin import child_env as claude_child_env

    monkeypatch.setenv("GITHUB_TOKEN", "kept-for-normal-sessions")
    monkeypatch.setenv("SOME_TOOL_CONFIG", "also-kept")
    spec = SessionSpec(
        "claude-cli",
        "model",
        "ws",
        str(tmp_path),
        agent_id="a1",
        env={"VARDE_TAINT_TOKEN": "taint"},
    )

    env = claude_child_env(spec)

    assert env["GITHUB_TOKEN"] == "kept-for-normal-sessions"
    assert env["SOME_TOOL_CONFIG"] == "also-kept"
    assert env["VARDE_TAINT_TOKEN"] == "taint"
    assert env["VARDE_AGENT_ID"] == "a1"
    assert child_environment({"X": "1"})["X"] == "1"
    assert "X" not in child_environment()


def test_restricted_launch_drops_what_a_normal_launch_keeps(monkeypatch, tmp_path):
    from varde_runner.plugins.claude_cli.plugin import child_env as claude_child_env

    monkeypatch.setenv("GITHUB_TOKEN", "must-not-reach-the-bot")
    spec = SessionSpec(
        "claude-cli", "model", "ws", str(tmp_path), profile="restricted", env={}
    )

    assert "GITHUB_TOKEN" not in claude_child_env(spec)
