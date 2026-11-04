# ruff: noqa: S105, S106 - fake secret values prove they never reach a child.
from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest
from fakes.plugin import FakePlugin
from test_claude_cli_plugin import make_plugin, next_kind
from varde_runner.bot_profile import (
    BOT_ROLE,
    ENV_ALLOWLIST,
    PROFILE_RESTRICTED,
    ProfileUnsupported,
    is_restricted,
    profile_for_role,
    restricted_environment,
    restricted_profile,
    valid_token,
)
from varde_runner.config import default_config
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.plugins.claude_cli.plugin import child_env
from varde_runner.plugins.claude_cli.wire import restricted_flags, tool_names
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.protocol import ResumeSettings
from varde_runner.supervisor import Supervisor

TOKEN = "bot-token-value-1234"


def bot_spec(tmp_path, **overrides) -> SessionSpec:
    fields = {
        "provider": "claude-cli",
        "model": "model-x",
        "workspace_id": "bot-ws",
        "cwd": str(tmp_path),
        "prompt": "",
        "mode_id": "full-access",  # must be ignored for a restricted session
        "agent_id": "agent-bot",
        "profile": PROFILE_RESTRICTED,
        "env": {"VARDE_BOT_TOKEN": TOKEN},
    }
    return SessionSpec(**{**fields, **overrides})


def test_profile_is_generic_read_only_shell_through_hook_no_network() -> None:
    profile = restricted_profile()
    assert profile.file_tools == ("read", "search", "list")
    assert profile.shell_tool == "shell"
    assert profile.network_tools == ()
    assert not profile.user_settings and not profile.extra_dirs
    assert profile.mode == "bot"
    assert profile_for_role(BOT_ROLE) == PROFILE_RESTRICTED
    assert profile_for_role("builder") is None
    assert is_restricted(PROFILE_RESTRICTED) and not is_restricted(None)


def test_restricted_environment_keeps_only_the_allowlist_and_the_token() -> None:
    source: dict[str, str] = dict.fromkeys(ENV_ALLOWLIST, "v")
    source.update(
        ANTHROPIC_API_KEY="k",
        AWS_SECRET_ACCESS_KEY="s",
        GITHUB_TOKEN="g",
        PASEO_AGENT_ID="p",
        VARDE_AGENT_ID="ambient",
        SSH_AUTH_SOCK="/sock",
    )
    env = restricted_environment(source, {"VARDE_BOT_TOKEN": TOKEN})
    assert set(env) == {*ENV_ALLOWLIST, "VARDE_BOT_TOKEN"}
    assert restricted_environment({}, None) == {}


@pytest.mark.parametrize("value", ["", "a b", "x;y", "$(id)", "a" * 201, None, 5])
def test_token_shape_rejects_unsafe_values(value) -> None:
    assert not valid_token(value)
    assert valid_token(TOKEN)


def test_claude_env_for_a_restricted_spec_is_allowlist_plus_token_and_identity(
    tmp_path, monkeypatch
) -> None:
    for name in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(name, "must-not-leak")
    monkeypatch.setenv("VARDE_AGENT_ID", "ambient-agent")
    env = child_env(bot_spec(tmp_path))
    assert env["VARDE_BOT_TOKEN"] == TOKEN
    assert env["VARDE_AGENT_ID"] == "agent-bot"
    assert env["VARDE_HARNESS"] == "claude-cli"
    extra = (
        set(env)
        - set(ENV_ALLOWLIST)
        - {
            "VARDE_BOT_TOKEN",
            "VARDE_AGENT_ID",
            "VARDE_HARNESS",
            "CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS",
        }
    )
    assert extra == set()
    assert "must-not-leak" not in json.dumps(env)


@pytest.mark.parametrize(
    "key",
    [
        "PATH", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN",
        "VARDE_AGENT_ID", "VARDE_HARNESS", "HOME",
    ],
)  # fmt: skip
def test_restricted_overlay_accepts_only_the_bot_token(tmp_path, key) -> None:
    with pytest.raises(ValueError, match="accept only"):
        restricted_environment({}, {"VARDE_BOT_TOKEN": TOKEN, key: "x"})
    with pytest.raises(ValueError, match="accept only"):
        child_env(bot_spec(tmp_path, env={key: "x"}))


@pytest.mark.parametrize("value", ["", "a b", "x;y", "$(id)", "a" * 201])
def test_restricted_overlay_rejects_a_malformed_token(value) -> None:
    with pytest.raises(ValueError, match="malformed"):
        restricted_environment({}, {"VARDE_BOT_TOKEN": value})


def test_set_env_overlay_rejects_other_keys_for_a_restricted_session(tmp_path) -> None:
    async def exercise() -> None:
        plugin = make_plugin(tmp_path)
        try:
            ref = await plugin.start(bot_spec(tmp_path))
            with pytest.raises(ValueError, match="accept only"):
                plugin.set_env_overlay(
                    ref, {"VARDE_BOT_TOKEN": TOKEN, "GITHUB_TOKEN": "x"}
                )
            plugin.set_env_overlay(ref, {"VARDE_BOT_TOKEN": "fresh-token"})
            spec = plugin._load_spec(ref)
            assert child_env(spec)["VARDE_BOT_TOKEN"] == "fresh-token"
        finally:
            await plugin.close()

    asyncio.run(exercise())


def test_a_normal_session_overlay_is_not_restricted(tmp_path) -> None:
    spec = bot_spec(tmp_path, profile=None, env={"VARDE_TAINT_TOKEN": "t"})
    assert child_env(spec)["VARDE_TAINT_TOKEN"] == "t"


def test_identity_variables_come_from_the_runner_not_the_overlay(tmp_path) -> None:
    env = child_env(bot_spec(tmp_path))
    assert env["VARDE_AGENT_ID"] == "agent-bot"
    assert env["VARDE_HARNESS"] == "claude-cli"


def test_wire_flags_have_no_user_settings_or_extra_dirs(tmp_path) -> None:
    flags = restricted_flags(
        "/state/x.bot-settings.json", tool_names(restricted_profile().tool_kinds)
    )
    assert flags == [
        "--restricted", "--tools", "Read,Grep,Glob,Bash", "--strict-mcp-config",
        "--safe-mode", "--settings", "/state/x.bot-settings.json",
    ]  # fmt: skip
    assert "--add-dir" not in flags
    with pytest.raises(ValueError):
        tool_names(("read", "browser"))


def test_session_spec_env_is_hidden_and_not_compared(tmp_path) -> None:
    spec = bot_spec(tmp_path)
    assert TOKEN not in repr(spec)
    assert spec == replace(spec, env={})


def capture_argv(monkeypatch) -> list[list[str]]:
    """Record each spawned argv; the restricted env hides the fake's own log."""
    captured: list[list[str]] = []
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        captured.append([str(item) for item in args])
        return await real(*args, **kwargs)

    monkeypatch.setattr(
        "varde_runner.plugins.claude_cli.plugin.asyncio.create_subprocess_exec", spy
    )
    return captured


def test_restricted_launch_argv_persisted_spec_and_restart(
    tmp_path, monkeypatch
) -> None:
    captured = capture_argv(monkeypatch)

    async def exercise() -> None:
        state = tmp_path / "state"
        first = make_plugin(tmp_path, state_dir=state)
        later = make_plugin(tmp_path, state_dir=state)
        try:
            ref = await first.start(bot_spec(tmp_path))
            await next_kind(first.events(ref), "text")
            await first.close()
            persisted = (state / f"{ref.session_id}.json").read_text()
            assert TOKEN not in persisted
            assert json.loads(persisted)["profile"] == PROFILE_RESTRICTED
            settings = json.loads(
                (state / f"{ref.session_id}.bot-settings.json").read_text()
            )
            assert settings == {
                "permissions": {"allow": [], "deny": ["WebFetch", "WebSearch"]}
            }
            # A fresh plugin (runner restart) resumes still restricted and has no token.
            await later.resume(SessionRef(ref.provider, ref.session_id))
            await next_kind(later.events(ref), "text")
            assert len(captured) == 2
            for argv in captured:
                assert (
                    "--restricted" in argv
                    and "--safe-mode" in argv
                    and "--strict-mcp-config" in argv
                )
                assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob,Bash"
                assert argv[argv.index("--permission-mode") + 1] == "manual"
                assert "--add-dir" not in argv
                assert argv.count("--settings") == 1
                assert argv[argv.index("--settings") + 1].endswith(".bot-settings.json")
            assert "--resume" in captured[1]
            assert child_env(later._load_spec(ref)).get("VARDE_BOT_TOKEN") is None
            later.set_env_overlay(ref, {"VARDE_BOT_TOKEN": "reissued-token"})
            assert (
                child_env(later._load_spec(ref))["VARDE_BOT_TOKEN"] == "reissued-token"
            )
            with pytest.raises(ValueError, match="restricted"):
                await later.resume(ref, ResumeSettings(mode_id="full-access"))
        finally:
            await first.close()
            await later.close()

    asyncio.run(exercise())


def test_a_normal_launch_is_not_restricted(tmp_path, monkeypatch) -> None:
    captured = capture_argv(monkeypatch)

    async def exercise() -> None:
        plugin = make_plugin(tmp_path)
        try:
            spec = bot_spec(tmp_path, profile=None, env={}, mode_id="workspace-write")
            ref = await plugin.start(spec)
            await next_kind(plugin.events(ref), "text")
            argv = captured[0]
            assert "--restricted" not in argv and "--settings" not in argv
            assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
        finally:
            await plugin.close()

    asyncio.run(exercise())


def test_unknown_profile_name_is_refused_at_spawn(tmp_path) -> None:
    async def exercise() -> None:
        plugin = make_plugin(tmp_path)
        try:
            with pytest.raises(RuntimeError, match="unsupported session profile"):
                await plugin.start(bot_spec(tmp_path, profile="other"))
        finally:
            await plugin.close()

    asyncio.run(exercise())


def build_supervisor(
    tmp_path, monkeypatch, capabilities
) -> tuple[Supervisor, FakePlugin]:
    config = replace(default_config(), stall_after_s=10)
    monkeypatch.setattr("varde_runner.supervisor.load_config", lambda *_: config)
    plugin = FakePlugin(capabilities)
    registry = PluginRegistry(["claude_cli"])
    registry.register("claude_cli", plugin)
    supervisor = Supervisor(tmp_path, registry)
    asyncio.run(supervisor.start())
    return supervisor, plugin


def test_supervisor_refuses_a_restricted_launch_on_an_adapter_without_the_profile(
    tmp_path, monkeypatch
) -> None:
    supervisor, plugin = build_supervisor(
        tmp_path, monkeypatch, RunnerCapabilities(resume=True)
    )
    spec = bot_spec(tmp_path, provider="claude_cli", env={})
    with pytest.raises(ProfileUnsupported):
        asyncio.run(supervisor.start_session(spec, BOT_ROLE))
    assert plugin.started == []


def test_supervisor_accepts_a_restricted_launch_when_the_adapter_supports_it(
    tmp_path, monkeypatch
) -> None:
    supervisor, plugin = build_supervisor(
        tmp_path, monkeypatch, RunnerCapabilities(resume=True, restricted_profile=True)
    )
    spec = bot_spec(tmp_path, provider="claude_cli", env={})
    ref = asyncio.run(supervisor.start_session(spec, BOT_ROLE))
    assert plugin.started[0].profile == PROFILE_RESTRICTED
    with pytest.raises(Exception, match="restricted session cannot change mode"):
        asyncio.run(supervisor.set_mode(ref.session_id, "system:dashboard", "auto"))
