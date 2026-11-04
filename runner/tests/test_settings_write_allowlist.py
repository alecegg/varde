from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from varde_runner.config import default_toml
from varde_runner.plugins.paseo import PaseoPlugin
from varde_runner.runner_config_edit import allowlist
from varde_runner.web import registry as registry_module
from varde_runner.web.runner_config_route import create_runner_config_routes


class Registry:
    def plugins(self):
        return [SimpleNamespace(config_table="claude_sdk")]

    def config_tables(self):
        return {"claude_sdk"}

    def known_harnesses(self):
        return {"claude-sdk", "codex-app-server", "pi-rpc", "opencode-http"}


class Request:
    def __init__(self, payload=None):
        self.payload = payload

    async def json(self):
        return self.payload


class Response:
    def __init__(self, response):
        self.status_code = response.status_code
        self.body = json.loads(response.body)

    def json(self):
        return self.body


def _routes(tmp_path: Path):
    config_file = tmp_path / "runner.toml"
    config_file.write_text(default_toml(), encoding="utf-8")
    return config_file, create_runner_config_routes(
        Registry,
        config_file=lambda: config_file,
        state_root=lambda: tmp_path / "state",
    )


def _call(tmp_path: Path, method: str, payload=None):
    _path, routes = _routes(tmp_path)
    route = next(route for route in routes if method in (route.methods or set()))
    response = asyncio.run(route.endpoint(Request(payload)))
    return Response(response)


def test_write_route_rejects_credentials_commands_paths_and_unknown_keys(tmp_path):
    _path, _routes_list = _routes(tmp_path)
    original = (tmp_path / "runner.toml").read_text(encoding="utf-8")
    forbidden = {
        "bot.api_key": "not-a-secret",
        "claude_sdk.token": "not-a-secret",
        "claude_sdk.binary": "tool",
        "claude_sdk.command": "run",
        "claude_sdk.path": "relative/tool",
        "claude_sdk.dir": "relative/config",
        "unknown.enabled": True,
        "runner.require_user_pairing": True,
        "runner.idle_process_timeout_s": 0,
    }

    for key, value in forbidden.items():
        response = _call(tmp_path, "PUT", {"changes": {key: value}})
        assert response.status_code == 400
        assert key in response.json()["errors"]

    assert (tmp_path / "runner.toml").read_text(encoding="utf-8") == original
    assert not (tmp_path / "state/config-changes.jsonl").exists()


def test_get_route_exposes_only_allowlisted_values(tmp_path):
    response = _call(tmp_path, "GET")

    assert response.status_code == 200
    items = response.json()["items"]
    keys = {item["key"] for item in items}
    assert keys == {
        "limits.max_live_instances",
        "claude_sdk.enabled",
        "roles.builder.type",
        "roles.manager-bot.type",
        "roles.explorer.type",
        "roles.planner.type",
        "roles.reviewer.type",
        "roles.judge.type",
        "roles.guard.type",
        "roles.guard.enabled",
        "roles.orchestrator.type",
        "policy.never_models",
        "policy.allow_fallback_only_on",
    }
    assert all("token" not in key for key in keys)


def test_disabled_native_harnesses_are_editable_and_enable_after_restart(
    tmp_path, monkeypatch
):
    config_file = tmp_path / "runner.toml"
    text = default_toml()
    config_file.write_text(text, encoding="utf-8")
    monkeypatch.setattr(registry_module, "config_path", lambda: config_file)

    disabled_registry = registry_module.build_registry(
        plugin=PaseoPlugin.from_environment()
    )
    fields = allowlist(disabled_registry, text)
    assert {
        "claude_cli.enabled",
        "claude_sdk.enabled",
        "codex_app_server.enabled",
        "opencode_http.enabled",
        "pi_durable.enabled",
        "pi_rpc.enabled",
    } <= fields.keys()
    assert "claude-cli" not in disabled_registry.harnesses()

    enabled_text = text.replace(
        "[claude_cli]\nenabled = false", "[claude_cli]\nenabled = true"
    )
    config_file.write_text(enabled_text, encoding="utf-8")
    restarted_registry = registry_module.build_registry(
        plugin=PaseoPlugin.from_environment()
    )
    assert isinstance(
        restarted_registry.plugin_for("claude-cli"),
        registry_module.ClaudeCliPlugin,
    )


def test_rejected_response_never_echoes_config_or_request_values(tmp_path):
    response = _call(tmp_path, "PUT", {"changes": {"bot.api_key": "sensitive-value"}})

    assert response.status_code == 400
    assert "sensitive-value" not in json.dumps(response.json())
    assert default_toml() not in json.dumps(response.json())
