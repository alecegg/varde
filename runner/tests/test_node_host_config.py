from __future__ import annotations

from pathlib import Path

import pytest
from varde_runner.config import ConfigError
from varde_runner.node_host_config import (
    NodeHostSettings,
    node_host_engine_path,
    node_host_settings,
)

RUNNER_ROOT = Path(__file__).resolve().parents[1]


def test_node_host_settings_defaults_and_explicit_values() -> None:
    assert node_host_settings("version = 1") == NodeHostSettings()
    assert node_host_settings(
        '[node_host]\nnode = "/opt/node/bin/node"\n'
        "restart_max = 5\nrestart_window_s = 120\ncall_timeout_s = 15.5\n"
    ) == NodeHostSettings("/opt/node/bin/node", 5, 120.0, 15.5)


@pytest.mark.parametrize(
    "text",
    [
        "node_host = true",
        '[node_host]\nnode = " "',
        "[node_host]\nrestart_max = true",
        "[node_host]\nrestart_max = -1",
        "[node_host]\nrestart_window_s = 0",
        "[node_host]\ncall_timeout_s = false",
    ],
)
def test_node_host_settings_rejects_invalid_values(text: str) -> None:
    with pytest.raises(ConfigError):
        node_host_settings(text)


def test_engine_path_defaults_under_runner_package_and_resolves_overrides() -> None:
    assert node_host_engine_path("fake") == (
        RUNNER_ROOT / "node-host" / "engines" / "fake" / "index.mjs"
    )
    assert node_host_engine_path("fake", "custom/engine.mjs") == (
        RUNNER_ROOT / "custom" / "engine.mjs"
    )


def test_engine_path_rejects_traversal() -> None:
    with pytest.raises(ConfigError, match="simple path component"):
        node_host_engine_path("../outside")
