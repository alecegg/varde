from __future__ import annotations

import pytest
from varde_runner.config import (
    ConfigError,
    default_toml,
    parse_config,
    pi_durable_settings,
)
from varde_runner.plugins.pi_durable import PiDurablePlugin
from varde_runner.web.registry import build_registry


def _enabled_config() -> str:
    return default_toml().replace(
        "[pi_durable]\nenabled = false", "[pi_durable]\nenabled = true"
    )


def test_pi_durable_is_opt_in_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    assert "pi-durable" not in build_registry().harnesses()


def test_pi_durable_registers_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "runner.toml").write_text(_enabled_config())
    plugin = build_registry().plugin_for("pi-durable")
    assert isinstance(plugin, PiDurablePlugin)
    assert plugin.settings.provider == "anthropic"


def test_pi_durable_harness_requires_enablement():
    config = default_toml().replace(
        'harness = "codex-app-server"\nmodel = "gpt-6-luna"',
        'harness = "pi-durable"\nmodel = "anthropic/claude-sonnet-4-5"',
        1,
    )
    with pytest.raises(ConfigError, match="pi-durable harness is disabled"):
        parse_config(config)


def test_pi_durable_settings_validate_key_name_and_provider_model_pair():
    with pytest.raises(ConfigError, match="environment variable name"):
        pi_durable_settings(
            '[pi_durable]\nenabled=true\nprovider="anthropic"\n'
            'model="anthropic/claude"\nkey_env="bad-name"'
        )
    with pytest.raises(ConfigError, match="must match"):
        pi_durable_settings(
            '[pi_durable]\nenabled=true\nprovider="anthropic"\n'
            'model="openai/gpt"\nkey_env="OPENAI_API_KEY"'
        )
