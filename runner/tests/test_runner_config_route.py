from __future__ import annotations

import asyncio
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
import varde_runner.web.registry as registry_module
from varde_runner.config import default_toml
from varde_runner.plugins.paseo import PaseoPlugin
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.web.registry import build_registry
from varde_runner.web.runner_config_route import (
    ROUTE_POLICIES,
    create_runner_config_routes,
)


class Registry:
    def config_tables(self):
        return {"claude_sdk"}

    def known_harnesses(self):
        return {
            "claude-cli",
            "claude-sdk",
            "codex-app-server",
            "opencode-http",
            "pi-rpc",
        }

    def config_choices(self, harness):
        values = {
            "claude-sdk": {
                "models": ["claude-sonnet-5-5"],
                "reasoning_efforts": ["low", "medium", "high"],
            },
            "codex-app-server": {
                "models": ["gpt-6-luna"],
                "reasoning_efforts": ["low", "medium", "high"],
            },
            "opencode-http": {
                "models": ["opencode-go/deepseek-v4.1-flash"],
                "reasoning_efforts": ["high"],
            },
        }
        for choices in values.values():
            choices["harnesses"] = list(values)
        return values.get(
            harness, {"harnesses": [], "models": [], "reasoning_efforts": []}
        )

    def capabilities(self, harness):
        return SimpleNamespace(guard_read_only=harness == "codex-app-server")


class Request:
    def __init__(self, payload=None):
        self.payload = payload

    async def json(self):
        return self.payload


class Response:
    def __init__(self, response):
        self.status_code = response.status_code
        self.body = json.loads(response.body)


def _setup(tmp_path: Path):
    config_file = tmp_path / "runner.toml"
    config_file.write_text(default_toml(), encoding="utf-8")
    routes = create_runner_config_routes(
        Registry,
        config_file=lambda: config_file,
        state_root=lambda: tmp_path / "state",
    )
    return config_file, routes


def _call(routes, method: str, payload=None) -> Response:
    route = next(route for route in routes if method in (route.methods or set()))
    return Response(asyncio.run(route.endpoint(Request(payload))))


def test_settings_route_policy_and_pairing_default():
    assert ROUTE_POLICIES[("PUT", "/api/runner/config")] == "user_only"
    assert tomllib.loads(default_toml())["runner"]["require_user_pairing"] is False


def test_get_exposes_structured_type_role_guard_and_policy_fields(tmp_path):
    _config, routes = _setup(tmp_path)

    response = _call(routes, "GET")

    assert response.status_code == 200
    items = {item["key"]: item for item in response.body["items"]}
    assert items["types.standard.harness"]["type"] == "string"
    assert items["types.standard.fallback"]["type"] == "array"
    assert items["roles.guard.enabled"]["value"] is False
    assert items["policy.never_models"]["value"] == ["*-sol"]
    assert all("token" not in key for key in items)


def test_get_exposes_policy_items_with_production_registry(tmp_path, monkeypatch):
    config_file = tmp_path / "runner.toml"
    config_file.write_text(default_toml(), encoding="utf-8")
    monkeypatch.setattr(registry_module, "config_path", lambda: config_file)
    plugin = PaseoPlugin(tmp_path / "unused.sock", "ws://127.0.0.1:1/ws")
    registry = build_registry(plugin=plugin)
    routes = create_runner_config_routes(
        lambda: registry,
        config_file=lambda: config_file,
        state_root=lambda: tmp_path / "state",
    )

    response = _call(routes, "GET")

    assert response.status_code == 200
    items = {item["key"]: item for item in response.body["items"]}
    assert items["policy.never_models"]["value"] == ["*-sol"]
    assert items["policy.allow_fallback_only_on"]["value"] == ["provider_limit"]
    assert any(key.startswith("types.") for key in items)
    assert any(key.startswith("roles.") for key in items)
    assert response.body["choices"]
    assert set(response.body["choices"]) >= registry.known_harnesses()


def test_plugin_registry_config_choices_delegates_and_rejects_unknown_harness():
    class Plugin:
        def config_choices(self, harness):
            assert harness == "example"
            return {"models": ["model-a", 4], "modes": ["read-only"]}

    registry = PluginRegistry()
    registry.register("example", Plugin())

    assert registry.config_choices("example") == {
        "harnesses": [],
        "models": ["model-a"],
        "reasoning_efforts": [],
        "modes": ["read-only"],
    }
    with pytest.raises(KeyError):
        registry.config_choices("unknown")


def test_preview_does_not_write_config_backup_or_audit(tmp_path):
    config_file, routes = _setup(tmp_path)
    original = config_file.read_bytes()

    response = _call(
        routes,
        "PUT",
        {"preview": True, "changes": {"types.standard.reasoning_effort": "high"}},
    )

    assert response.status_code == 200
    assert response.body["preview"] is True
    assert response.body["changed"] == ["types.standard.reasoning_effort"]
    assert response.body["restart_required"] is True
    assert config_file.read_bytes() == original
    assert list(tmp_path.glob("runner.toml.*.bak")) == []
    assert not (tmp_path / "state/config-changes.jsonl").exists()


def test_allowed_hosts_and_invalid_cross_field_changes_leave_config_unchanged(tmp_path):
    config_file, routes = _setup(tmp_path)
    original = config_file.read_bytes()
    before_backups = sorted(path.name for path in tmp_path.glob("runner.toml.*.bak"))

    for preview in (False, True):
        for changes in (
            {"allowed_hosts": ["SENSITIVE-HOST-4831"]},
            {"roles.builder.type": "missing-type"},
            {"roles.guard.type": "standard", "roles.guard.enabled": True},
        ):
            response = _call(routes, "PUT", {"preview": preview, "changes": changes})
            assert response.status_code == 400
            assert config_file.read_bytes() == original
            assert (
                sorted(path.name for path in tmp_path.glob("runner.toml.*.bak"))
                == before_backups
            )


def test_valid_edit_saves_atomically_audits_and_returns_restart_metadata(tmp_path):
    config_file, routes = _setup(tmp_path)
    sentinel = "SENSITIVE-SENTINEL-4831"

    response = _call(
        routes,
        "PUT",
        {"changes": {"types.standard.reasoning_effort": "high"}},
    )

    assert response.status_code == 200
    assert response.body["restart_required"] is True
    assert (
        tomllib.loads(config_file.read_text())["types"]["standard"]["reasoning_effort"]
        == "high"
    )
    assert len(list(tmp_path.glob("runner.toml.*.bak"))) == 1
    audit = (tmp_path / "state/config-changes.jsonl").read_text()
    assert '"key":"types.standard.reasoning_effort"' in audit
    assert sentinel not in json.dumps(response.body) + audit


def test_rejected_sensitive_field_does_not_echo_submitted_value(tmp_path):
    _config, routes = _setup(tmp_path)
    sentinel = "SENSITIVE-SENTINEL-4831"

    response = _call(routes, "PUT", {"changes": {"config.path": sentinel}})

    assert response.status_code == 400
    assert sentinel not in json.dumps(response.body)
    assert not (tmp_path / "state/config-changes.jsonl").exists()
