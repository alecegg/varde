"""Read-only runner and registered harness status."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from varde_data.errors import Invalid
from varde_data.queue_paths import queue_migration_pending

from varde_runner.agent_launch import data_root
from varde_runner.config import DEFAULT_ROLE_TYPES, TYPE_DEFINITIONS, config_path

_STARTED_AT = time.monotonic()
CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def _run_command(
    command: Sequence[str], timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - registered plugin owns the executable.
        list(command),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _login_status(
    plugin: Any, runner: CommandRunner, timeout: float = 3.0
) -> tuple[str, str]:
    args = getattr(plugin, "login_status_args", None)
    executable = getattr(plugin, "executable", None)
    binary_name = getattr(plugin, "login_status_binary", None)
    if not isinstance(args, tuple) or not isinstance(binary_name, str):
        return "unknown", "This harness has no safe login status probe."
    binary = (
        str(executable)
        if executable and Path(str(executable)).is_absolute()
        else shutil.which(str(executable or binary_name))
    )
    if not binary or not Path(binary).exists():
        return "missing", "Install the harness command to check login status."
    try:
        result = runner([binary, *args], timeout)
    except OSError, subprocess.TimeoutExpired:
        return "unknown", "The harness login status could not be checked."
    output = f"{result.stdout}\n{result.stderr}".casefold()
    if any(
        phrase in output
        for phrase in (
            "not logged in",
            "not authenticated",
            "not signed in",
            "login required",
            "authentication required",
        )
    ):
        return "login_required", "Log in with the harness command."
    if result.returncode == 0 and any(
        phrase in output for phrase in ("logged in", "authenticated", "signed in")
    ):
        return "ready", "Harness reports an active login."
    return "unknown", "The harness did not provide a recognized login status."


def _service_state(home: Path, marker: str | None) -> dict[str, Any]:
    kind = marker if marker in {"launchd", "systemd"} else None
    installed = (home / "Library/LaunchAgents/org.varde.runner.plist").is_file() or (
        home / ".config/systemd/user/varde-runner.service"
    ).is_file()
    return {
        "managed": kind is not None,
        "kind": kind,
        "installed": installed,
    }


def build_status(
    registry: Any,
    working_dir: Path,
    *,
    command_runner: CommandRunner = _run_command,
    home: Path | None = None,
) -> dict[str, Any]:
    """Build status from the active registry without exposing command output."""
    root = data_root(working_dir).expanduser().resolve()
    harnesses = []
    enabled = registry.harnesses()
    for name in sorted(enabled):
        plugin = registry.plugin_for(name)
        executable = getattr(plugin, "executable", None)
        found = (
            Path(str(executable)).is_file()
            if executable and Path(str(executable)).is_absolute()
            else shutil.which(str(executable)) is not None
            if executable
            else True
        )
        login, hint = _login_status(plugin, command_runner)
        harnesses.append(
            {
                "name": name,
                "enabled": True,
                "binary_found": found,
                "login": login if found else "missing",
                "hint": hint if found else "Install the harness command.",
            }
        )
    default_harnesses = {
        TYPE_DEFINITIONS[type_name][0] for type_name in DEFAULT_ROLE_TYPES.values()
    }
    default_roles_enabled = default_harnesses <= set(enabled)
    try:
        version = importlib.metadata.version("varde-runner")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    try:
        pending = queue_migration_pending(working_dir)
    except Invalid as error:
        queue_status = f"queue migration status unavailable: {error}"
    else:
        queue_status = (
            "queue migration pending: run varde plan queue merge-role-inbox"
            if pending
            else None
        )
    return {
        "version": version,
        "uptime_s": max(0, int(time.monotonic() - _STARTED_AT)),
        "config_path": str(config_path().expanduser()),
        "data_root": str(root),
        "service": _service_state(
            home or Path.home(), os.environ.get("VARDE_RUNNER_SERVICE")
        ),
        "harnesses": harnesses,
        "default_roles_enabled": default_roles_enabled,
        "queue_status": queue_status,
    }
