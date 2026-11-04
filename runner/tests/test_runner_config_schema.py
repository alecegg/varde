from __future__ import annotations

import asyncio
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

from varde_runner.config import default_toml
from varde_runner.web.runner_config_route import create_runner_config_routes
from varde_runner.web.runner_config_schema import config_choices


class Registry:
    def known_harnesses(self):
        return {"alpha", "beta"}

    def config_choices(self, harness):
        return {
            "alpha": {
                "harnesses": ["alpha", "beta"],
                "models": ["alpha-model"],
                "reasoning_efforts": ["quiet", "deep"],
                "modes": ["read-only"],
            },
            "beta": {
                "harnesses": ["alpha", "beta"],
                "models": ["beta-model"],
                "reasoning_efforts": ["brief"],
                "modes": ["workspace-write"],
            },
        }[harness]


def test_choices_are_scoped_to_each_registered_harness():
    choices = config_choices(Registry())

    assert choices["alpha"]["models"] == ["alpha-model"]
    assert choices["alpha"]["reasoning_efforts"] == ["quiet", "deep"]
    assert choices["alpha"]["modes"] == ["read-only"]
    assert choices["beta"]["models"] == ["beta-model"]
    assert choices["beta"]["reasoning_efforts"] == ["brief"]
    assert choices["beta"]["modes"] == ["workspace-write"]
    assert "beta-model" not in choices["alpha"]["models"]
    assert "alpha-model" not in choices["beta"]["models"]


def test_registry_choices_are_normalized_without_inventing_options():
    class NoChoices:
        def known_harnesses(self):
            return {"alpha"}

    assert config_choices(NoChoices()) == {}


def test_save_rejects_a_model_not_offered_for_its_harness(tmp_path: Path):
    class RouteRegistry(Registry):
        def known_harnesses(self):
            return {
                "claude-cli",
                "claude-sdk",
                "codex-app-server",
                "opencode-http",
                "pi-rpc",
            }

        def config_tables(self):
            return set()

        def config_choices(self, harness):
            choices = {
                "claude-sdk": {
                    "harnesses": ["claude-sdk", "codex-app-server"],
                    "models": ["claude-sonnet-5-5"],
                    "reasoning_efforts": ["low", "medium", "high"],
                    "modes": ["workspace-write", "read-only"],
                },
                "codex-app-server": {
                    "harnesses": ["claude-sdk", "codex-app-server"],
                    "models": ["gpt-6-luna"],
                    "reasoning_efforts": ["low", "medium", "high"],
                    "modes": ["workspace-write", "read-only"],
                },
                "opencode-http": {
                    "harnesses": ["claude-sdk", "codex-app-server"],
                    "models": ["opencode-go/deepseek-v4.1-flash"],
                    "reasoning_efforts": ["high"],
                    "modes": ["workspace-write", "read-only"],
                },
            }
            return choices.get(
                harness,
                {"harnesses": [], "models": [], "reasoning_efforts": [], "modes": []},
            )

        def capabilities(self, harness):
            return SimpleNamespace(guard_read_only=harness == "codex-app-server")

    class Request:
        async def json(self):
            return {"changes": {"types.standard.model": "gpt-6-luna"}}

    config_file = tmp_path / "runner.toml"
    config_file.write_text(default_toml(), encoding="utf-8")
    original = config_file.read_bytes()
    routes = create_runner_config_routes(
        RouteRegistry,
        config_file=lambda: config_file,
        state_root=lambda: tmp_path / "state",
    )
    read_route = next(route for route in routes if "GET" in (route.methods or set()))
    read_response = asyncio.run(read_route.endpoint(Request()))
    assert json.loads(read_response.body)["choices"]["claude-sdk"]["models"] == [
        "claude-sonnet-5-5"
    ]
    route = next(route for route in routes if "PUT" in (route.methods or set()))

    response = asyncio.run(route.endpoint(Request()))
    result = json.loads(response.body)

    assert response.status_code == 400
    assert config_file.read_bytes() == original
    assert list(tmp_path.glob("runner.toml.*.bak")) == []
    assert not (tmp_path / "state/config-changes.jsonl").exists()
    assert (
        tomllib.loads(config_file.read_text())["types"]["standard"]["model"]
        == "claude-sonnet-5-5"
    )
    assert "gpt-6-luna" not in json.dumps(result)
