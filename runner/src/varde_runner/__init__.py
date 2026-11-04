"""Varde agent runner entry point."""

import argparse
import os
import sys
import time
import urllib.request
import uuid
from http.client import IncompleteRead
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from urllib.error import HTTPError, URLError

import uvicorn

from varde_runner.clients import ClientRole
from varde_runner.config import (
    ConfigError,
    adapter_state_root,
    config_path,
    configured_allowed_hosts,
)

GRACEFUL_SHUTDOWN_TIMEOUT = 5


def _installed_version() -> str:
    try:
        return distribution_version("varde-runner")
    except PackageNotFoundError:
        return "unknown"


VERSION = _installed_version()


def installed_runner_path() -> str:
    """Return the stable user install path, or the current runner executable."""
    stable_path = Path.home() / ".local" / "bin" / "varde-runner"
    if stable_path.is_file():
        return str(stable_path)
    return sys.argv[0]


def merge_allowed_hosts(*values: str) -> frozenset[str]:
    """Normalize comma-separated host values from every source into one set."""
    return frozenset(
        host.strip().lower()
        for value in values
        for host in value.split(",")
        if host.strip()
    )


def _config_allowed_hosts() -> tuple[str, ...]:
    try:
        text = config_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return ()
    try:
        return configured_allowed_hosts(text)
    except ConfigError as exc:
        raise SystemExit(f"{config_path()}: {exc}") from exc


def main() -> None:
    if sys.argv[1:2] == ["--version"]:
        print(VERSION)
        return
    if sys.argv[1:2] == ["agent"]:
        from varde_runner.agent_cli import main as agent_main

        agent_main(sys.argv[2:])
        return
    if sys.argv[1:2] == ["workspace"]:
        from varde_runner.workspace_cli import main as workspace_main

        workspace_main(sys.argv[2:])
        return
    if sys.argv[1:2] == ["gate"]:
        from varde_runner.gate_cli import main as gate_main

        raise SystemExit(gate_main(sys.argv[2:]))
    if sys.argv[1:2] == ["pairing-code"]:
        _pairing_code()
        return
    if sys.argv[1:2] == ["service"]:
        from varde_runner.service import main as service_main

        service_main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(prog="varde-runner")
    parser.add_argument("command", choices=("serve", "watch"))
    parser.add_argument("agent", nargs="?")
    parser.add_argument("--host", choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allowed-host", action="append")
    parser.add_argument("--after", type=int)
    parser.add_argument("--writer", action="store_true")
    args = parser.parse_args()
    if args.command == "watch":
        if not args.agent:
            parser.error("watch requires an agent id")
        if args.host is not None or args.allowed_host is not None:
            parser.error("--host and --allowed-host require the serve command")
        if args.after is not None and args.after < 0:
            parser.error("--after must not be negative")
        _watch(args.agent, args.after, args.writer, args.port)
        return
    if args.agent is not None or args.after is not None or args.writer:
        parser.error("watch options require the watch command")
    os.environ.setdefault("VARDE_RUNNER_RELAY", "data")
    working = os.environ.get("VARDE_WORKING_DIR")
    if not working:
        raise SystemExit("VARDE_WORKING_DIR must point to a Varde working directory")

    from varde_runner.config import config_path, configured_user_pairing, default_toml
    from varde_runner.user_credential import UserCredential
    from varde_runner.web import create_app

    credential = UserCredential(credential_path())
    runner_config_path = config_path()
    runner_config_text = (
        runner_config_path.read_text(encoding="utf-8")
        if runner_config_path.exists()
        else default_toml()
    )
    require_user_pairing = configured_user_pairing(runner_config_text)
    if require_user_pairing:
        code = credential.start(time.time())
        if code is not None:
            _announce_pairing(code)

    uvicorn.run(
        create_app(
            data_dir=Path(working) / ".cache" / "dashboard",
            bound_port=args.port,
            user_credential=credential,
            require_user_pairing=require_user_pairing,
            allowed_hosts=merge_allowed_hosts(
                *_config_allowed_hosts(),
                *(args.allowed_host or []),
                os.environ.get("VARDE_RUNNER_ALLOWED_HOSTS", ""),
            ),
        ),
        host=args.host or "127.0.0.1",
        port=args.port,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT,
    )


def credential_path() -> Path:
    return adapter_state_root() / "user-credential.json"


def _announce_pairing(code: str, require_user_pairing: bool = True) -> None:
    """Show the code only on a terminal; a service log is readable by agents."""
    if not require_user_pairing:
        return
    if sys.stdout.isatty():
        print(f"Varde pairing code (enter once in the browser): {code}", flush=True)
        return
    print(
        "Varde runner is not paired: run `varde-runner pairing-code` for the code.",
        flush=True,
    )


def _pairing_code() -> None:
    from varde_runner.user_credential import read_pairing_code

    code = read_pairing_code(credential_path())
    if code is None:
        raise SystemExit("No pairing code: this runner is paired or has not started.")
    print(code)


def _watch(agent: str, after: int | None, writer: bool, port: int) -> None:
    from varde_runner.web.agent_watch import watch_url

    role = ClientRole.WRITER if writer else ClientRole.OBSERVER
    url = watch_url(
        agent,
        after=after,
        client=f"watch-cli-{uuid.uuid4().hex}",
        role=role,
        port=port,
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if line.startswith("data: "):
                    print(line[6:], file=sys.stdout, flush=True)
    except HTTPError as exc:
        raise SystemExit(f"watch request failed: HTTP {exc.code}") from exc
    except URLError as exc:
        raise SystemExit(f"watch request failed: {exc.reason}") from exc
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (OSError, IncompleteRead) as exc:
        raise SystemExit(f"watch stream interrupted: {exc}") from None
