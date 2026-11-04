"""The ``varde runner`` command: flip the runner switch and the runner service."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from varde_data.config import runner_switch_state, set_runner_enabled
from varde_data.errors import Invalid

_EXECUTABLE = "varde-runner"
_LAUNCHD_LABEL = "org.varde.runner"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="varde runner",
        description="Turn the runner switch and service off or on",
    )
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser(
        "off", help="Write the switch off, then stop the runner service"
    )
    commands.add_parser("on", help="Start the runner service, then write the switch on")
    commands.add_parser(
        "status", help="Show the switch value, its source and the service"
    )
    return parser


def _executable() -> str | None:
    found = shutil.which(_EXECUTABLE)
    if found:
        return found
    stable = Path.home() / ".local" / "bin" / _EXECUTABLE
    return str(stable) if stable.is_file() else None


def _service_installed() -> bool:
    if sys.platform == "darwin":
        unit = Path.home() / "Library/LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
    else:
        unit = Path.home() / ".config/systemd/user/varde-runner.service"
    return unit.is_file()


def _service(executable: str, action: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed varde-runner service action.
        [executable, "service", action],
        capture_output=True,
        text=True,
        check=False,
    )


def _detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip() or f"exit {result.returncode}"


def _write_switch(value: bool) -> None:
    set_runner_enabled(value)
    print(f"runner switch: {'on' if value else 'off'}")
    effective = runner_switch_state()[0]
    if effective != value:
        print(
            "warning: VARDE_RUNNER_ENABLED overrides config.toml; "
            f"the effective value stays {'on' if effective else 'off'}",
            file=sys.stderr,
        )


def _off() -> int:
    _write_switch(False)
    executable = _executable()
    if executable is None:
        print(f"note: {_EXECUTABLE} not found; no service to stop")
        return 0
    if not _service_installed():
        print("note: runner service is not installed; nothing to stop")
        return 0
    result = _service(executable, "stop")
    if result.returncode:
        print(
            f"warning: runner service stop failed: {_detail(result)}", file=sys.stderr
        )
        return 1
    print("runner service: stopped")
    return 0


def _on() -> int:
    executable = _executable()
    if executable is None:
        print(f"runner: {_EXECUTABLE} not found; switch unchanged", file=sys.stderr)
        return 1
    result = _service(executable, "start")
    if result.returncode:
        print(
            f"runner: service start failed, switch unchanged: {_detail(result)}",
            file=sys.stderr,
        )
        return 1
    print("runner service: started")
    _write_switch(True)
    return 0


def _status() -> int:
    value, source = runner_switch_state()
    print(f"runner switch: {'on' if value else 'off'} (source: {source})")
    file_value, file_source = runner_switch_state(env={})
    if source == "env" and file_source == "file" and file_value != value:
        print(
            "warning: VARDE_RUNNER_ENABLED overrides config.toml "
            f"([runner] enabled = {str(file_value).lower()})",
            file=sys.stderr,
        )
    executable = _executable()
    if executable is None:
        print(f"runner service: {_EXECUTABLE} not found")
        return 0
    result = _service(executable, "status")
    print(f"runner service status (exit {result.returncode}):")
    print((result.stdout or result.stderr).strip())
    return 0


def run(argv: list[str], io: object) -> int:
    """Run a runner command and return its process exit status."""
    del io
    try:
        action = _parser().parse_args(argv).action
        return {"off": _off, "on": _on, "status": _status}[action]()
    except SystemExit as error:
        return int(error.code or 0)
    except (OSError, Invalid) as error:
        print(f"runner: {error}", file=sys.stderr)
        return 1
