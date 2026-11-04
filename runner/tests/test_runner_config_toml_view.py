from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

from varde_runner.web.runner_config_toml_view import (
    config_view,
    create_runner_config_toml_view_route,
    redact_runner_config,
)


def test_redacts_credentials_binary_paths_commands_and_environment_values():
    source = """
allowed_hosts = ["runner.example.test"]
api_token = "TOKEN-SENTINEL-41"
[codex_app_server]
binary = "/opt/BINARY-SENTINEL-41"
[workspace]
config_path = "/PATH-SENTINEL-41"
command = "COMMAND-SENTINEL-41"
[environment]
API_KEY = "ENV-SENTINEL-41"
"""

    result = redact_runner_config(source)

    for sentinel in (
        "TOKEN-SENTINEL-41",
        "BINARY-SENTINEL-41",
        "PATH-SENTINEL-41",
        "COMMAND-SENTINEL-41",
        "ENV-SENTINEL-41",
    ):
        assert sentinel not in result
    assert 'allowed_hosts = ["runner.example.test"]' in result


def test_invalid_toml_is_omitted_without_echoing_input():
    sentinel = "INVALID-SECRET-SENTINEL-41"
    assert sentinel not in redact_runner_config(f'password = "{sentinel}\n')
    assert "Invalid TOML" in redact_runner_config('password = "broken')


def test_config_view_includes_sanitized_text_and_allowed_hosts():
    view = config_view(
        'allowed_hosts = ["runner.example.test"]\npassword = "SECRET-41"\n'
    )
    assert view["allowed_hosts"] == ["runner.example.test"]
    assert view["path"] == ""
    assert "SECRET-41" not in cast("str", view["toml"])


def test_get_route_returns_only_read_only_view_fields(tmp_path: Path):
    path = tmp_path / "runner.toml"
    path.write_text(
        'allowed_hosts = ["runner.example.test"]\npassword = "SECRET-42"\n',
        encoding="utf-8",
    )
    route = create_runner_config_toml_view_route(config_file=path)

    class Request:
        pass

    response = asyncio.run(route.endpoint(Request()))
    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["allowed_hosts"] == ["runner.example.test"]
    assert body["path"] == str(path)
    assert "SECRET-42" not in body["toml"]
