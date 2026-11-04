from __future__ import annotations

import pytest
from varde_runner.config import ConfigError, default_toml, parse_config
from varde_runner.plugins.pi_rpc.plugin import PiRpcPlugin
from varde_runner.web.registry import build_registry


def test_pi_rpc_enabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    assert "pi-rpc" in build_registry().harnesses()


def test_pi_rpc_registers_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    config = default_toml().replace(
        "[pi_rpc]\nenabled = true", "[pi_rpc]\nenabled = false"
    )
    (tmp_path / "runner.toml").write_text(config, encoding="utf-8")
    assert "pi-rpc" not in build_registry().harnesses()
    (tmp_path / "runner.toml").write_text(
        config.replace("[pi_rpc]\nenabled = false", "[pi_rpc]\nenabled = true"),
        encoding="utf-8",
    )
    assert isinstance(build_registry().plugin_for("pi-rpc"), PiRpcPlugin)


def test_pi_rpc_config_rejects_approval_required_role():
    config = default_toml().replace(
        "[pi_rpc]\nenabled = false", "[pi_rpc]\nenabled = true"
    )
    config = config.replace(
        'harness = "codex-app-server"\nmodel = "gpt-6-luna"',
        'harness = "pi-rpc"\nmodel = "gpt-6-luna"',
        1,
    )
    with pytest.raises(ConfigError, match="pi-rpc.*requires approvals"):
        parse_config(config)


def _pi_type_config() -> str:
    return """
version = 1

[pi_rpc]
enabled = true

[policy]
never_models = []
allow_fallback_only_on = ["provider_limit"]
create_paseo_projects = false

[types.pi_read_only]
harness = "pi-rpc"
model = "model"
reasoning_effort = "medium"
mode = "read-only"

[[types.pi_read_only.fallback]]
harness = "pi-rpc"
model = "model"
reasoning_effort = "medium"
mode = "read-only"

[roles.builder]
type = "pi_read_only"
"""


@pytest.mark.parametrize(
    "effort", ("off", "minimal", "low", "medium", "high", "xhigh", "max")
)
def test_pi_rpc_allows_supported_reasoning_efforts(effort):
    config = _pi_type_config().replace(
        'reasoning_effort = "medium"', f'reasoning_effort = "{effort}"'
    )
    assert parse_config(config).resolve("builder").mode == "read-only"


def test_pi_rpc_rejects_unsupported_reasoning_effort_clearly():
    config = _pi_type_config().replace(
        'reasoning_effort = "medium"', 'reasoning_effort = "very-high"'
    )
    with pytest.raises(ConfigError, match="Pi RPC reasoning_effort must be one of"):
        parse_config(config)


def test_pi_rpc_approval_error_precedes_generic_type_mode_error():
    config = _pi_type_config().replace(
        'mode = "read-only"', 'mode = "workspace-write"', 1
    )
    with pytest.raises(ConfigError, match="pi-rpc.*requires approvals"):
        parse_config(config)
