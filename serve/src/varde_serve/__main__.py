"""Run the serve command: `varde-serve` or `python -m varde_serve`."""

from __future__ import annotations

import sys

from varde_core.io import Io

USAGE = "usage: varde-serve [start | stop | status | mcp | daemon | --version]"


def main(argv: list[str] | None = None, io: Io | None = None) -> int:
    """Route one subcommand; the `varde serve` paths call this executable."""
    del io
    args = sys.argv[1:] if argv is None else argv
    if args == ["--version"]:
        from varde_serve.version import serve_version

        sys.stdout.write(f"varde-serve {serve_version()}\n")
        return 0
    command = args[0] if args else "start"
    if len(args) > 1 or command not in COMMANDS:
        sys.stderr.write(f"{USAGE}\n")
        return 2
    return COMMANDS[command]()


def _start() -> int:
    from varde_serve.commands import start

    return start()


def _stop() -> int:
    from varde_serve.commands import stop

    return stop()


def _status() -> int:
    from varde_serve.commands import status

    return status()


def _mcp() -> int:
    from varde_serve.mcp.shim import main as mcp_main

    return mcp_main()


def _daemon() -> int:
    from varde_serve.daemon.entry import run_here

    return run_here()


COMMANDS = {
    "start": _start,
    "stop": _stop,
    "status": _status,
    "mcp": _mcp,
    "daemon": _daemon,
}

if __name__ == "__main__":
    raise SystemExit(main())
