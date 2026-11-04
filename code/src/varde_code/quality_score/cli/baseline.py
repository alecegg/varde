"""``varde code quality``: the local baseline page and the reference scores."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path
from typing import Any, TextIO


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="varde code quality baseline")
    commands = parser.add_subparsers(dest="command", required=True)
    ui = commands.add_parser("ui", help="serve the local baseline page")
    ui.add_argument("--port", type=int, default=0, help="loopback port (0 = free)")
    ui.add_argument("--no-open", action="store_true", help="do not open a browser")
    ui.add_argument(
        "--debug", action="store_true", help="include raw scorer fields in the page"
    )
    ui.add_argument("--data", type=Path, help=argparse.SUPPRESS)
    return parser


def _reference_parser() -> argparse.ArgumentParser:
    from .reference import add_parsers

    parser = argparse.ArgumentParser(prog="varde code quality reference")
    add_parsers(parser.add_subparsers(dest="command", required=True))
    return parser


def run(argv: list[str], io: Any = None) -> int:
    """``argv`` starts ``["quality", "baseline"|"reference", ...]``."""
    stdout: TextIO = getattr(io, "stdout", sys.stdout)
    stderr: TextIO = getattr(io, "stderr", sys.stderr)
    if argv[:2] == ["quality", "reference"]:
        from .reference import run as run_reference

        return run_reference(_reference_parser().parse_args(argv[2:]), io)
    if argv[:2] != ["quality", "baseline"]:
        print(
            "usage: varde code quality baseline ui | reference build|show", file=stderr
        )
        return 2
    args = _parser().parse_args(argv[2:])
    from . import baseline_service as svc
    from .baseline_server import serve

    data = svc.BaselineData(args.data or svc.DEFAULT_DATA)
    if not data.calibration_path.is_file():
        print(f"code quality baseline: no baseline data at {data.root}", file=stderr)
        return 2

    def ready(url: str) -> None:
        print(url, file=stdout, flush=True)
        if not args.no_open:
            webbrowser.open(url)

    serve(data, args.port, args.debug, ready)
    return 0
