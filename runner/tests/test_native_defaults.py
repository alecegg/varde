from __future__ import annotations

from varde_runner.config import default_toml, parse_config
from varde_runner.web.registry import build_registry


def test_default_roles_use_native_harnesses_and_write_fallback() -> None:
    config = parse_config(default_toml())
    assert config.resolve("orchestrator").harness == "claude-sdk"
    assert config.resolve("builder").harness == "codex-app-server"
    assert config.resolve("builder").fallback[0].harness == "opencode-http"
    assert (
        config.resolve("builder").fallback[0].model == "opencode-go/deepseek-v4.1-flash"
    )
    assert config.resolve("guard").harness == "codex-app-server"


def test_native_harnesses_are_enabled_and_cli_is_disabled_by_default(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    registry = build_registry()
    assert {"claude-sdk", "codex-app-server", "pi-rpc", "opencode-http"} <= (
        registry.harnesses()
    )
    assert "claude-cli" not in registry.harnesses()


def test_false_codex_enabled_keeps_paseo_provider_key(tmp_path, monkeypatch) -> None:
    from varde_runner.plugins.paseo import PaseoPlugin

    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    config = default_toml().replace(
        "[codex_app_server]\nenabled = true", "[codex_app_server]\nenabled = false"
    )
    (tmp_path / "runner.toml").write_text(config, encoding="utf-8")
    registry = build_registry(
        PaseoPlugin(tmp_path / "runner.sock", "ws://127.0.0.1:6767/ws")
    )
    assert registry.provider_key("codex-app-server") == "codex"
