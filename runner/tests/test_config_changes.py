from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from varde_runner.config import default_toml
from varde_runner.web.runner_config_route import create_runner_config_routes


class Registry:
    def plugins(self):
        return [SimpleNamespace(config_table="claude_sdk")]

    def known_harnesses(self):
        return {"claude-sdk", "codex-app-server", "pi-rpc", "opencode-http"}

    def config_tables(self):
        return {"claude_sdk"}


class Request:
    def __init__(self, changes=None):
        self.changes = changes or {
            "limits.max_live_instances": 12,
            "claude_sdk.enabled": False,
        }

    async def json(self):
        return {"changes": self.changes}


def test_config_change_log_has_one_safe_record_per_changed_key(tmp_path: Path):
    config_file = tmp_path / "runner.toml"
    config_file.write_text(default_toml(), encoding="utf-8")
    routes = create_runner_config_routes(
        Registry,
        config_file=lambda: config_file,
        state_root=lambda: tmp_path / "state",
    )
    put_route = next(route for route in routes if "PUT" in (route.methods or set()))

    response = asyncio.run(put_route.endpoint(Request()))

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["restart_required"] is True
    assert {item["key"]: item["restart_required"] for item in payload["items"]}[
        "limits.max_live_instances"
    ] is False
    assert {item["key"]: item["restart_required"] for item in payload["items"]}[
        "claude_sdk.enabled"
    ] is True
    lines = (tmp_path / "state/config-changes.jsonl").read_text().splitlines()
    records = [json.loads(line) for line in lines]
    assert {record["key"] for record in records} == {
        "limits.max_live_instances",
        "claude_sdk.enabled",
    }
    assert len(records) == 2
    assert all(set(record) == {"ts", "key", "old", "new"} for record in records)
    assert all(isinstance(record["old"], (int, bool)) for record in records)
    assert all(isinstance(record["new"], (int, bool)) for record in records)
    assert all("free text" not in line and "token" not in line for line in lines)


def test_numeric_config_change_does_not_require_restart(tmp_path: Path):
    config_file = tmp_path / "runner.toml"
    config_file.write_text(default_toml(), encoding="utf-8")
    routes = create_runner_config_routes(
        Registry,
        config_file=lambda: config_file,
        state_root=lambda: tmp_path / "state",
    )
    put_route = next(route for route in routes if "PUT" in (route.methods or set()))

    response = asyncio.run(
        put_route.endpoint(Request({"limits.max_live_instances": 12}))
    )

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["restart_required"] is False
    assert {item["key"]: item["restart_required"] for item in payload["items"]}[
        "limits.max_live_instances"
    ] is False


def test_idle_timeout_is_no_longer_editable_through_settings_route(tmp_path: Path):
    config_file = tmp_path / "runner.toml"
    config_file.write_text(default_toml(), encoding="utf-8")
    routes = create_runner_config_routes(
        Registry,
        config_file=lambda: config_file,
        state_root=lambda: tmp_path / "state",
    )
    put_route = next(route for route in routes if "PUT" in (route.methods or set()))

    response = asyncio.run(
        put_route.endpoint(Request({"runner.idle_process_timeout_s": 0}))
    )

    assert response.status_code == 400
    assert json.loads(response.body)["errors"] == {
        "runner.idle_process_timeout_s": "this key is not allowlisted"
    }
