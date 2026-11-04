import asyncio

import pytest
from varde_runner.config import (
    ConfigError,
    default_toml,
    opencode_http_settings,
    parse_config,
)
from varde_runner.plugins import SessionSpec
from varde_runner.plugins.opencode_http.plugin import OpenCodeHttpPlugin
from varde_runner.web.registry import build_registry


def test_opencode_http_is_enabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    assert "opencode-http" in build_registry().harnesses()
    assert opencode_http_settings(default_toml()) == (True, None)


def test_opencode_http_registers_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    config = default_toml().replace(
        "[opencode_http]\nenabled = true", "[opencode_http]\nenabled = false"
    )
    (tmp_path / "runner.toml").write_text(config, encoding="utf-8")
    assert "opencode-http" not in build_registry().harnesses()
    (tmp_path / "runner.toml").write_text(
        config.replace(
            "[opencode_http]\nenabled = false", "[opencode_http]\nenabled = true"
        ),
        encoding="utf-8",
    )
    assert isinstance(build_registry().plugin_for("opencode-http"), OpenCodeHttpPlugin)


def test_disabled_harness_and_unsupported_modes_fail_validation(tmp_path):
    config = (
        default_toml()
        .replace("[opencode_http]\nenabled = true", "[opencode_http]\nenabled = false")
        .replace('harness = "codex-app-server"', 'harness = "opencode-http"', 1)
    )
    with pytest.raises(ConfigError, match="opencode-http harness is disabled"):
        parse_config(config)
    plugin = OpenCodeHttpPlugin("opencode")
    with pytest.raises(RuntimeError, match="unsupported OpenCode mode"):
        asyncio.run(
            plugin.start(
                SessionSpec(
                    "opencode-http",
                    "model",
                    "agent",
                    str(tmp_path),
                    mode_id="invalid",
                )
            )
        )


def test_unsupported_opencode_mode_is_rejected_during_config_parse():
    config = default_toml().replace(
        "[opencode_http]\nenabled = true", "[opencode_http]\nenabled = true"
    )
    config = config.replace(
        'harness = "codex-app-server"\nmodel = "gpt-6-luna"',
        'harness = "opencode-http"\nmodel = "gpt-6-luna"\nmode = "danger-full-access"',
        1,
    )
    with pytest.raises(
        ConfigError, match="mode is not supported by native opencode-http"
    ):
        parse_config(config)
