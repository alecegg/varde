from __future__ import annotations

from varde_runner.config import ConfigError, claude_sdk_settings, default_toml
from varde_runner.web.registry import build_registry


def test_claude_sdk_config_defaults_and_validates() -> None:
    assert claude_sdk_settings(default_toml()) == (True, 300)
    assert claude_sdk_settings(
        "[claude_sdk]\nenabled=true\nstream_idle_timeout_s=90"
    ) == (True, 90)


def test_claude_sdk_config_rejects_invalid_values() -> None:
    import pytest

    with pytest.raises(ConfigError, match="enabled must be a boolean"):
        claude_sdk_settings("[claude_sdk]\nenabled='yes'")
    with pytest.raises(ConfigError, match="must be positive"):
        claude_sdk_settings("[claude_sdk]\nstream_idle_timeout_s=0")
    with pytest.raises(ConfigError, match="must be positive"):
        claude_sdk_settings("[claude_sdk]\nstream_idle_timeout_s=inf")


def test_native_plugin_replaces_paseo_route_when_enabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "runner.toml").write_text(
        default_toml().replace(
            "[claude_sdk]\nenabled = true\nstream_idle_timeout_s = 300",
            "[claude_sdk]\nenabled = false\nstream_idle_timeout_s = 300",
        ),
        encoding="utf-8",
    )
    (tmp_path / "runner.toml").write_text(
        (tmp_path / "runner.toml")
        .read_text(encoding="utf-8")
        .replace("[claude_sdk]\nenabled = false", "[claude_sdk]\nenabled = true"),
        encoding="utf-8",
    )
    registry = build_registry()
    assert "claude-sdk" in registry.harnesses()
    assert registry.provider_key("claude-sdk") == "claude-sdk"


def test_paseo_route_remains_when_native_plugin_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "runner.toml").write_text(
        default_toml().replace(
            "[claude_sdk]\nenabled = true\nstream_idle_timeout_s = 300",
            "[claude_sdk]\nenabled = false\nstream_idle_timeout_s = 300",
        ),
        encoding="utf-8",
    )
    registry = build_registry()
    assert "claude-sdk" in registry.harnesses()
    assert registry.provider_key("claude-sdk") == "claude"
