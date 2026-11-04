from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from varde_runner.config import ConfigError, default_toml, parse_config
from varde_runner.plugins.codex_app_server.plugin import CodexAppServerPlugin
from varde_runner.plugins.paseo import PaseoPlugin
from varde_runner.supervisor import Supervisor
from varde_runner.web.registry import build_registry


def test_codex_app_server_is_native_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    paseo = PaseoPlugin(tmp_path / "runner.sock", "ws://127.0.0.1:6767/ws")
    registry = build_registry(paseo)
    assert parse_config(default_toml()).roles
    assert isinstance(registry.plugin_for("codex-app-server"), CodexAppServerPlugin)
    assert registry.provider_key("claude-sdk") == "claude-sdk"


def test_disabled_codex_keeps_paseo_route(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "runner.toml").write_text(
        default_toml().replace(
            "[codex_app_server]\nenabled = true",
            "[codex_app_server]\nenabled = false",
        ),
        encoding="utf-8",
    )
    paseo = PaseoPlugin(tmp_path / "runner.sock", "ws://127.0.0.1:6767/ws")
    registry = build_registry(paseo)
    assert getattr(registry.plugin_for("codex-app-server"), "_plugin", None) is paseo


def test_codex_app_server_registers_with_configured_binary(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "runner.toml").write_text(
        default_toml().replace(
            "[codex_app_server]\nenabled = true",
            '[codex_app_server]\nenabled = true\nbinary = "/opt/codex"',
        ),
        encoding="utf-8",
    )
    plugin = build_registry().plugin_for("codex-app-server")
    assert isinstance(plugin, CodexAppServerPlugin)
    assert plugin.executable == "/opt/codex"


def test_codex_role_uses_its_type_and_fixed_mode():
    builder = parse_config(default_toml()).resolve("builder")
    assert builder.harness == "codex-app-server"
    assert builder.mode == "workspace-write"


def test_model_type_rejects_configured_mode():
    config = default_toml().replace(
        '[types.light]\nharness = "codex-app-server"',
        '[types.light]\nharness = "codex-app-server"\nmode = "danger-full-access"',
    )
    with pytest.raises(ConfigError, match="types.light.mode is not configurable"):
        parse_config(config)


def test_enabled_codex_without_binary_has_clear_startup_error(tmp_path, monkeypatch):
    async def start():
        monkeypatch.setenv("PATH", "")
        plugin = CodexAppServerPlugin(state_dir=tmp_path)
        from varde_runner.plugins import SessionSpec

        with pytest.raises(RuntimeError, match="codex executable not found on PATH"):
            await plugin.start(
                SessionSpec("codex-app-server", "model", "workspace", str(tmp_path))
            )

    asyncio.run(start())


def test_supervisor_sweeps_plugin_orphans(tmp_path):
    class Sweeper:
        capabilities = SimpleNamespace(resume=False)

        async def recover_orphans(self):
            return {"orphan-session"}

        async def close(self):
            return None

    async def run():
        supervisor = Supervisor(tmp_path / "sessions", {"codex-app-server": Sweeper()})
        supervisor.store.create_session(
            "stored-session",
            "codex-app-server",
            {"provider": "codex-app-server", "session_id": "orphan-session"},
            "builder",
        )
        await supervisor.start()
        try:
            row = supervisor.store.get_session("stored-session")
            assert row is not None
            assert row["status"] == "error"
            assert any(
                event["kind"] == "error"
                for event in supervisor.store.events_after("stored-session", 0)
            )
        finally:
            await supervisor.shutdown()

    asyncio.run(run())
