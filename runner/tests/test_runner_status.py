from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from starlette.requests import Request
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.runner_status import build_status
from varde_runner.web.runner_status_route import (
    ROUTE_POLICIES,
    create_runner_status_routes,
)


class _StatusPlugin:
    executable: str
    login_status_binary = "fake-harness"
    login_status_args = ("auth", "status")

    def __init__(self, executable: Path) -> None:
        self.executable = str(executable)


def _registry(executable: Path) -> PluginRegistry:
    registry = PluginRegistry(["test-harness"])
    registry.register("test-harness", _StatusPlugin(executable))
    return registry


def test_status_reports_metadata_and_only_login_status_word(
    tmp_path: Path, monkeypatch: Any
) -> None:
    binary = tmp_path / "fake-harness"
    binary.touch()
    commands: list[tuple[list[str], float]] = []

    def run(command: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
        command_list = list(command)
        commands.append((command_list, timeout))
        return subprocess.CompletedProcess(
            command_list, 0, "Logged in as private@example.test", ""
        )

    monkeypatch.delenv("VARDE_RUNNER_SERVICE", raising=False)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    status = build_status(
        _registry(binary),
        tmp_path,
        command_runner=run,
        home=tmp_path / "home",
    )

    assert status["version"]
    assert status["uptime_s"] >= 0
    assert status["config_path"].endswith("runner.toml")
    assert status["data_root"] == str(tmp_path)
    assert status["service"] == {"managed": False, "kind": None, "installed": False}
    assert status["harnesses"] == [
        {
            "name": "test-harness",
            "enabled": True,
            "binary_found": True,
            "login": "ready",
            "hint": "Harness reports an active login.",
        }
    ]
    assert commands == [([str(binary), "auth", "status"], 3.0)]
    assert "private@example.test" not in repr(status)


def test_unknown_login_never_opens_credentials(
    tmp_path: Path, monkeypatch: Any
) -> None:
    binary = tmp_path / "fake-harness"
    binary.touch()
    credential = tmp_path / "auth.json"
    credential.write_text("must not be read")
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        assert path != credential
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    status = build_status(
        _registry(binary),
        tmp_path,
        command_runner=lambda command, timeout: subprocess.CompletedProcess(
            command, 0, "unexpected private response", ""
        ),
    )

    assert status["harnesses"][0]["login"] == "unknown"
    assert "unexpected private response" not in repr(status)


def test_not_logged_in_is_not_misclassified_as_ready(tmp_path: Path) -> None:
    binary = tmp_path / "fake-harness"
    binary.touch()
    status = build_status(
        _registry(binary),
        tmp_path,
        command_runner=lambda command, timeout: subprocess.CompletedProcess(
            command, 1, "Not logged in", ""
        ),
    )

    assert status["harnesses"][0]["login"] == "login_required"


def test_runner_status_exposes_pending_queue_migration(tmp_path: Path) -> None:
    marker = tmp_path / ".cache/data/queue.version"
    marker.parent.mkdir(parents=True)
    marker.write_text("3\n", encoding="ascii")

    status = build_status(_registry(tmp_path / "missing"), tmp_path)

    assert status["queue_status"] == (
        "queue migration pending: run varde plan queue merge-role-inbox"
    )


def test_status_and_restart_routes_have_read_and_user_only_policies(
    tmp_path: Path, monkeypatch: Any
) -> None:
    registry = _registry(tmp_path / "missing-binary")
    stopped: list[bool] = []
    routes = create_runner_status_routes(
        lambda: registry, tmp_path, restart=lambda: stopped.append(True)
    )
    restart_route = routes[1]

    assert ROUTE_POLICIES == {
        ("GET", "/api/runner/status"): "read",
        ("POST", "/api/runner/restart"): "user_only",
    }
    home = tmp_path / "home"
    service = home / ".config/systemd/user/varde-runner.service"
    service.parent.mkdir(parents=True)
    service.touch()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("VARDE_RUNNER_SERVICE", raising=False)
    status_route = routes[0]
    response = asyncio.run(status_route.endpoint(cast("Request", object())))
    assert json.loads(response.body)["service"] == {
        "managed": False,
        "kind": None,
        "installed": True,
    }
    response = asyncio.run(restart_route.endpoint(cast("Request", object())))
    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload["error"] == "not_managed"
    assert "varde-runner service start" in payload["hint"]
    assert stopped == []

    monkeypatch.setenv("VARDE_RUNNER_SERVICE", "systemd")
    response = asyncio.run(restart_route.endpoint(cast("Request", object())))
    assert response.status_code == 202
    assert response.background is not None
    asyncio.run(response.background())
    assert stopped == [True]
    status_route = routes[0]
    response = asyncio.run(status_route.endpoint(cast("Request", object())))
    assert json.loads(response.body)["service"]["managed"] is True


def test_installed_but_not_supervising_is_not_managed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    home = tmp_path / "home"
    service = home / ".config/systemd/user/varde-runner.service"
    service.parent.mkdir(parents=True)
    service.touch()
    monkeypatch.delenv("VARDE_RUNNER_SERVICE", raising=False)
    status = build_status(_registry(tmp_path / "missing"), tmp_path, home=home)
    assert status["service"] == {"managed": False, "kind": None, "installed": True}
    assert status["harnesses"][0]["login"] == "missing"
