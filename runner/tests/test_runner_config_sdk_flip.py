from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from varde_runner.web.runner_config_sdk_flip import (
    ROUTE_POLICIES,
    create_sdk_flip_routes,
)

FIXTURE = Path(__file__).parent / "fixtures/live_runner_legacy.toml"


class Registry:
    def __init__(self, known=None):
        self._known = known or {
            "claude-cli",
            "claude-sdk",
            "codex-app-server",
            "opencode-http",
            "pi-rpc",
        }

    def known_harnesses(self):
        return self._known

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


def _setup(tmp_path: Path, registry=None):
    config_file = tmp_path / "runner.toml"
    config_file.write_bytes(FIXTURE.read_bytes())
    routes = create_sdk_flip_routes(
        lambda: registry or Registry(),
        config_file=lambda: config_file,
        state_root=lambda: tmp_path / "state",
    )
    return config_file, routes


def _call(routes, suffix: str, payload=None):
    route = next(route for route in routes if route.path.endswith(suffix))
    return Response(asyncio.run(route.endpoint(Request(payload))))


def test_sdk_flip_routes_are_user_only():
    assert (
        ROUTE_POLICIES[("POST", "/api/runner/config/sdk-flip/preview")] == "user_only"
    )
    assert ROUTE_POLICIES[("POST", "/api/runner/config/sdk-flip/apply")] == "user_only"


def test_preview_returns_reviewed_diff_without_mutating_config_or_backups(tmp_path):
    config_file, routes = _setup(tmp_path)
    original = config_file.read_bytes()

    response = _call(routes, "/preview")

    assert response.status_code == 200
    assert response.body["preview_id"]
    assert response.body["restart_required"] is True
    assert {row["key"] for row in response.body["diff"]} == {
        "claude_cli.enabled",
        "types.standard.harness",
        "types.heavy.harness",
        "claude_sdk.enabled",
        "claude_sdk.stream_idle_timeout_s",
        "roles.manager-bot.type",
        "roles.manager-bot.enabled",
    }
    assert config_file.read_bytes() == original
    assert list(tmp_path.glob("runner.toml.*.bak")) == []
    assert not (tmp_path / "state/config-changes.jsonl").exists()


def test_apply_requires_confirmation_and_reviewed_preview(tmp_path):
    config_file, routes = _setup(tmp_path)
    original = config_file.read_bytes()

    response = _call(routes, "/apply", {"preview_id": "unused"})

    assert response.status_code == 400
    assert "confirmation" in response.body["error"]
    assert config_file.read_bytes() == original
    assert list(tmp_path.glob("runner.toml.*.bak")) == []


def test_confirmed_apply_writes_only_patch_keys_and_one_backup(tmp_path):
    config_file, routes = _setup(tmp_path)
    preview = _call(routes, "/preview")

    response = _call(
        routes,
        "/apply",
        {"confirm": True, "preview_id": preview.body["preview_id"]},
    )

    assert response.status_code == 200
    assert response.body["restart_required"] is True
    expected = {
        "claude_cli.enabled",
        "types.standard.harness",
        "types.heavy.harness",
        "claude_sdk.enabled",
        "claude_sdk.stream_idle_timeout_s",
        "roles.manager-bot.type",
        "roles.manager-bot.enabled",
    }
    assert set(response.body["changed"]) == expected
    assert len(list(tmp_path.glob("runner.toml.*.bak"))) == 1
    text = config_file.read_text(encoding="utf-8")
    assert "[claude_cli]\nenabled = false" in text
    assert '[types.standard]\nharness = "claude-sdk"' in text
    assert '[types.heavy]\nharness = "claude-sdk"' in text
    assert "[claude_sdk]\nenabled = true\nstream_idle_timeout_s = 300" in text
    assert '[roles.manager-bot]\ntype = "standard"\nenabled = false' in text
    assert '[[types.standard.fallback]]\nharness = "opencode-http"' in text
    audit = (tmp_path / "state/config-changes.jsonl").read_text(encoding="utf-8")
    assert {json.loads(line)["key"] for line in audit.splitlines()} == expected
    assert "ANTHROPIC_API_KEY" not in audit + json.dumps(response.body)


def test_invalid_candidate_is_refused_without_writing(tmp_path):
    config_file, routes = _setup(tmp_path)
    invalid = config_file.read_text(encoding="utf-8").replace(
        'harness = "opencode-http"', 'harness = "missing-harness"'
    )
    config_file.write_text(invalid, encoding="utf-8")
    original = config_file.read_bytes()

    response = _call(routes, "/preview")

    assert response.status_code == 400
    assert config_file.read_bytes() == original
    assert list(tmp_path.glob("runner.toml.*.bak")) == []
    assert not (tmp_path / "state/config-changes.jsonl").exists()


def test_stale_preview_cannot_apply(tmp_path):
    config_file, routes = _setup(tmp_path)
    preview = _call(routes, "/preview")
    config_file.write_text(config_file.read_text() + "\n# changed after preview\n")
    changed = config_file.read_bytes()

    response = _call(
        routes,
        "/apply",
        {"confirm": True, "preview_id": preview.body["preview_id"]},
    )

    assert response.status_code == 409
    assert config_file.read_bytes() == changed
    assert list(tmp_path.glob("runner.toml.*.bak")) == []
