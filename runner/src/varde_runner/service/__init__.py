"""Generated service definitions and user service management."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError

from varde_runner import installed_runner_path

LABEL = "org.varde.runner"


def resolve_working_dir(value: Path | None) -> Path:
    """Return the data root for the service: the option, else VARDE_WORKING_DIR."""
    raw = value or os.environ.get("VARDE_WORKING_DIR")
    if not raw:
        raise SystemExit(
            "Pass --working-dir or set VARDE_WORKING_DIR: the service data root "
            "must match the one `varde msg` and plans use."
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise SystemExit(f"Working directory must be an absolute path: {raw}")
    if not path.is_dir():
        raise SystemExit(f"Working directory does not exist: {path}")
    return path.resolve()


def _service_environment(
    working_dir: Path | None, relay: bool, service_kind: str
) -> dict[str, str]:
    environment = {}
    if working_dir:
        environment["VARDE_WORKING_DIR"] = str(working_dir)
    if relay:
        environment["VARDE_RUNNER_RELAY"] = "1"
    environment["VARDE_RUNNER_SERVICE"] = service_kind
    return environment


def _serve_arguments(port: int | None) -> list[str]:
    if port is None:
        return ["serve"]
    if not 1 <= port <= 65535:
        raise SystemExit(f"Invalid port: {port}")
    return ["serve", "--port", str(port)]


def render_launchd(
    executable: str | Path | None = None,
    home: Path | None = None,
    *,
    working_dir: Path | None = None,
    port: int | None = None,
    relay: bool = False,
) -> str:
    """Render a launch agent plist for the installed runner."""
    use_installed_path = home is None and executable is None
    home = home or Path.home()
    executable = str(
        executable
        or (installed_runner_path() if use_installed_path else _stable_executable(home))
    )
    value = {
        "Label": LABEL,
        "ProgramArguments": [executable, *_serve_arguments(port)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "EnvironmentVariables": {
            **_service_environment(working_dir, relay, "launchd"),
            "PATH": _service_path(home),
        },
        "StandardOutPath": str(home / "Library/Logs/Varde/runner.log"),
        "StandardErrorPath": str(home / "Library/Logs/Varde/runner-error.log"),
    }
    return plistlib.dumps(value).decode()


def render_systemd(
    *,
    home: Path | None = None,
    executable: str | Path | None = None,
    working_dir: Path | None = None,
    port: int | None = None,
    relay: bool = False,
) -> str:
    """Render a systemd user unit; the flags override the environment file."""
    use_installed_path = home is None and executable is None
    home = home or Path.home()
    executable = str(
        executable
        or (installed_runner_path() if use_installed_path else _stable_executable(home))
    )
    overrides = "".join(
        f'Environment="{key}={_unit_quote(value)}"\n'
        for key, value in _service_environment(working_dir, relay, "systemd").items()
    )
    arguments = " ".join(_serve_arguments(port))
    return (
        "[Unit]\nDescription=Varde runner\n\n[Service]\nType=simple\n"
        f'Environment="PATH={_unit_quote(_service_path(home))}"\n'
        f"EnvironmentFile=-{home / '.config/varde/runner.env'}\n"
        f"{overrides}"
        f'ExecStart="{_unit_quote(executable)}" {arguments}\n'
        "Restart=always\n\n[Install]\nWantedBy=default.target\n"
    )


def _unit_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return escaped.replace("%", "%%").replace("$", "$$")


def _stable_executable(home: Path) -> Path:
    return home / ".local/bin/varde-runner"


def run_service(args: list[str]) -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="varde-runner service")
    actions = parser.add_subparsers(dest="action", required=True)
    print_parser = actions.add_parser("print")
    print_parser.add_argument("platform", choices=("launchd", "systemd-user"))
    for parser_with_options in (print_parser, actions.add_parser("install")):
        parser_with_options.add_argument("--working-dir", type=Path)
        parser_with_options.add_argument("--port", type=int)
        parser_with_options.add_argument("--enable-relay", action="store_true")
    actions.add_parser("uninstall")
    actions.add_parser("status")
    actions.add_parser("start")
    actions.add_parser("stop")
    doctor_parser = actions.add_parser("doctor")
    doctor_parser.add_argument("--port", type=int, default=8765)
    parsed = parser.parse_args(args)
    if parsed.action == "print":
        options = {
            "working_dir": resolve_working_dir(parsed.working_dir),
            "port": parsed.port,
            "relay": parsed.enable_relay,
        }
        if parsed.platform == "launchd":
            print(render_launchd(**options))
        else:
            print(render_systemd(**options))
        return
    if parsed.action == "doctor":
        _doctor(parsed.port)
        return
    if parsed.action == "install":
        _manage(
            "install",
            working_dir=resolve_working_dir(parsed.working_dir),
            port=parsed.port,
            relay=parsed.enable_relay,
        )
        return
    _manage(parsed.action)


def _manage(
    action: str,
    *,
    working_dir: Path | None = None,
    port: int | None = None,
    relay: bool = False,
) -> None:
    import platform

    home = Path.home()
    options = {"working_dir": working_dir, "port": port, "relay": relay}
    executable = Path(installed_runner_path())
    if action == "install" and not executable.is_file():
        raise SystemExit(f"Runner executable not found: {executable}")
    if platform.system() == "Darwin":
        target = home / "Library/LaunchAgents" / f"{LABEL}.plist"
        if action == "install":
            target.parent.mkdir(parents=True, exist_ok=True)
            (home / "Library/Logs/Varde").mkdir(parents=True, exist_ok=True)
            target.write_text(
                render_launchd(executable=executable, home=home, **options)
            )
            _launchd_stop()
            _launchd_bootstrap(target)
        elif action == "uninstall":
            _launchd_stop()
            target.unlink(missing_ok=True)
        elif action == "stop":
            _launchd_stop()
        elif action == "start":
            if not target.is_file():
                raise SystemExit(
                    "Service not installed; run `varde-runner service install`"
                )
            _launchd_start(target)
        else:
            _launchd_status()
    else:
        target = home / ".config/systemd/user/varde-runner.service"
        if action == "install":
            target.parent.mkdir(parents=True, exist_ok=True)
            env_file = home / ".config/varde/runner.env"
            env_file.parent.mkdir(parents=True, exist_ok=True)
            _prepare_environment_file(env_file, home)
            target.write_text(
                render_systemd(home=home, executable=executable, **options)
            )
            _run(["systemctl", "--user", "daemon-reload"])
            _run(["systemctl", "--user", "enable", "--now", "varde-runner.service"])
            linger_command = [
                "loginctl",
                "enable-linger",
                os.environ.get("USER") or str(os.getuid()),
            ]
            linger = subprocess.run(linger_command, check=False)  # noqa: S603
            if linger.returncode:
                print(
                    "Could not enable lingering; the service may stop when you log out."
                )
        elif action == "uninstall":
            _run(
                ["systemctl", "--user", "disable", "--now", "varde-runner.service"],
                check=False,
            )
            target.unlink(missing_ok=True)
            _run(["systemctl", "--user", "daemon-reload"])
        elif action in ("start", "stop"):
            _run(["systemctl", "--user", action, "varde-runner.service"])
        else:
            _run(["systemctl", "--user", "status", "varde-runner.service"])
    if action in ("install", "start"):
        _default_runner_switch()


def _default_runner_switch() -> None:
    """Turn the runner switch on when unset; a bad config must not fail the service."""
    from varde_data.config import default_runner_enabled
    from varde_data.errors import Invalid

    try:
        default_runner_enabled()
    except Invalid as error:
        print(
            f"Runner switch not set: {error}; repair the config, "
            "then run `varde runner on`.",
            file=sys.stderr,
        )


LAUNCHD_NOT_LOADED = 113
LAUNCHD_UNLOAD_TIMEOUT = 15.0


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["launchctl", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )


def _launchd_domain() -> str:
    return f"gui/{os.getuid()}"


def _launchd_loaded() -> bool:
    result = _launchctl("print", f"{_launchd_domain()}/{LABEL}")
    if result.returncode == LAUNCHD_NOT_LOADED:
        return False
    if result.returncode:
        raise _launchd_fail("print", result)
    return True


def _launchd_wait_unloaded(timeout: float = LAUNCHD_UNLOAD_TIMEOUT) -> bool:
    """Poll until launchd forgets the job: bootout returns before it is gone."""
    deadline = time.monotonic() + timeout
    while _launchd_loaded():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)
    return True


def _launchd_fail(step: str, result: subprocess.CompletedProcess[str]) -> SystemExit:
    detail = (result.stderr or result.stdout or "").strip()
    return SystemExit(f"launchctl {step} failed (exit {result.returncode}): {detail}")


def _launchd_stop() -> None:
    _launchctl("bootout", f"{_launchd_domain()}/{LABEL}")
    if not _launchd_wait_unloaded():
        raise SystemExit(
            f"{LABEL} still loaded {LAUNCHD_UNLOAD_TIMEOUT:g}s after launchctl bootout"
        )


def _launchd_start(plist: Path) -> None:
    if not _launchd_loaded():
        _launchd_bootstrap(plist)
    result = _launchctl("kickstart", f"{_launchd_domain()}/{LABEL}")
    if result.returncode:
        raise _launchd_fail("kickstart", result)


def _launchd_bootstrap(plist: Path) -> None:
    result = _launchctl("bootstrap", _launchd_domain(), str(plist))
    if not result.returncode:
        return
    # A bootout still tearing down makes bootstrap fail; wait it out, retry once.
    _launchd_wait_unloaded(timeout=5.0)
    time.sleep(0.5)
    result = _launchctl("bootstrap", _launchd_domain(), str(plist))
    if result.returncode:
        raise _launchd_fail("bootstrap", result)


def _launchd_status() -> None:
    result = _launchctl("print", f"{_launchd_domain()}/{LABEL}")
    if result.returncode == LAUNCHD_NOT_LOADED:
        print(f"{LABEL} is not loaded")
        raise SystemExit(3)
    if result.returncode:
        raise _launchd_fail("print", result)
    print(result.stdout, end="")


def _run(command: list[str], *, check: bool = True) -> None:
    subprocess.run(command, check=check)  # noqa: S603 - Fixed command assembled by this module.


def _prepare_environment_file(env_file: Path, home: Path) -> None:
    if not env_file.exists():
        env_file.write_text(f"PATH={_service_path(home)}\n")
        return
    env_file.write_text(_without_install_keys(env_file.read_text()))


def _without_install_keys(text: str) -> str:
    """Drop keys set by install flags: systemd lets EnvironmentFile override them."""
    owned = ("VARDE_WORKING_DIR=", "VARDE_RUNNER_RELAY=")
    return "".join(
        line for line in text.splitlines(keepends=True) if not line.startswith(owned)
    )


def _service_path(home: Path) -> str:
    current = os.environ.get("PATH", "")
    candidates = [str(home / ".local/bin")]
    candidates.extend(
        str(Path(path).parent)
        for name in ("claude", "codex", "opencode", "pi")
        if (path := shutil.which(name))
    )
    return os.pathsep.join(dict.fromkeys([*candidates, *current.split(os.pathsep)]))


HTTP_FORBIDDEN = 403


def _shell_probe(probe_paths: Callable[[list[str], float], dict[str, str]]) -> dict:
    return {
        "results": probe_paths([os.getcwd()], 2.0),
        "message": "Shell probe complete; the result may differ from the service.",
    }


def _doctor(port: int = 8765) -> None:
    from varde_runner.service.probe import probe_paths

    url = f"http://127.0.0.1:{port}/api/probe"
    try:
        request = urllib.request.Request(
            url,
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - Fixed localhost HTTP endpoint.
            result = json.load(response)
    except HTTPError as error:
        if error.code != HTTP_FORBIDDEN:
            print(f"Runner probe failed with HTTP {error.code}: {error.reason}")
            return
        print(
            "The runner probe needs a paired browser; checking from this shell. "
            "The result may differ from the service."
        )
        result = _shell_probe(probe_paths)
    except URLError as error:
        if not isinstance(error.reason, (ConnectionRefusedError, FileNotFoundError)):
            print(f"Runner probe failed: {error.reason}")
            return
        print(
            "Runner unavailable; checking from this shell. "
            "The result may differ from the service."
        )
        result = _shell_probe(probe_paths)
    except TimeoutError:
        print(f"Runner probe timed out on port {port}.")
        return
    results = result.get("results", {})
    failed = {path: status for path, status in results.items() if status != "ok"}
    if failed:
        for path, status in failed.items():
            print(f"Workspace path {status}: {path}")
        if any(status == "timeout" for status in failed.values()):
            print(
                "An OS folder-access prompt may be pending. Runner executable: "
                f"{installed_runner_path()}; interpreter: {sys.executable}."
            )
    else:
        print(result.get("message", "Runner probe completed."))


main = run_service
