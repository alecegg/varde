"""Write and read entry points for the friction CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from . import cli_friction_read as read
from . import cli_friction_write as write
from .help import help_text


def run(argv: list[str], io: object | None = None) -> int:
    args = list(argv)
    root = args.pop(0) if args and args[0] in {"friction", "adopt"} else "friction"
    if not args:
        _write(io, help_text(root), error=True)
        return 2
    if args[0] in {"-h", "--help", "help"}:
        _write(io, help_text(root))
        return 0

    group = root if root == "adopt" else "friction"
    command = args.pop(0)
    path = f"adopt {command}" if group == "adopt" else f"friction {command}"
    handlers = {
        "friction list": read.run_list,
        "friction show": read.run_show,
        "friction export": read.run_export,
        "friction add": write.run_add_command,
        "friction set-status": write.run_set_status_command,
        "friction import": write.run_import_command,
        "adopt record": write.run_adopt_record_command,
        "adopt recurrence": read.run_adopt_recurrence,
    }
    if _wants_help(args):
        if path not in handlers:
            _write(io, _unknown_subcommand_error(root, command), error=True)
            return 2
        short_help = path == "friction add" and "-h" in args and "--help" not in args
        _write(io, _short_add_help() if short_help else help_text(path))
        return 0

    try:
        parsed = _parse(path, args)
    except (ValueError, argparse.ArgumentError) as error:
        message = str(error)
        if message.startswith("unrecognized arguments:"):
            message = _unexpected_argument_error(
                path, message.removeprefix("unrecognized arguments:").strip()
            )
        _write(
            io, message if message.endswith("\n") else f"error: {message}\n", error=True
        )
        return 2

    handler = handlers.get(path)
    if path == "friction import":
        source = Path(str(parsed.pop("source")))
        if parsed.get("repository") or source.is_dir():
            if not parsed.get("repository"):
                _write(
                    io,
                    "error: --repository is required for directory import\n",
                    error=True,
                )
                return 2
            parsed["directory"] = str(source)
            handler = write.run_import_command
        else:
            parsed["file"] = str(source)
            handler = write.run_event_import_command
    if handler is None:
        _write(io, _unknown_subcommand_error(root, command), error=True)
        return 2
    return int(handler(parsed, io))


def record_historical_capture(request: dict[str, Any]) -> dict[str, Any]:
    return write.record_historical_capture(request)


def _wants_help(args: list[str]) -> bool:
    return "-h" in args or "--help" in args


def _unknown_subcommand_error(root: str, command: str) -> str:
    group = "adopt" if root == "adopt" else "friction"
    return (
        f"error: unrecognized subcommand '{command}'\n\n"
        f"Usage: varde learn {group} <COMMAND>\n\n"
        "For more information, try '--help'.\n"
    )


def _unexpected_argument_error(path: str, arguments: str) -> str:
    argument = arguments.split()[0]
    if path == "friction list" and argument == "--rep":
        return (
            "error: unexpected argument '--rep' found\n\n"
            "  tip: a similar argument exists: '--repo'\n\n"
            "Usage: varde learn friction list --repository <ROOT>\n\n"
            "For more information, try '--help'.\n"
        )
    return (
        f"error: unexpected argument '{argument}' found\n\n"
        f"Usage: varde learn {path} [OPTIONS]\n\n"
        "For more information, try '--help'.\n"
    )


def _short_add_help() -> str:
    from pathlib import Path

    return (Path(__file__).parent / "help" / "friction" / "add-short.txt").read_text()


def _parse(path: str, args: list[str]) -> dict[str, Any]:
    parser = argparse.ArgumentParser(
        add_help=False, exit_on_error=False, allow_abbrev=False
    )
    parser.add_argument("--json", action="store_true")
    if path == "friction list":
        parser.add_argument("--status")
        parser.add_argument("--source")
        parser.add_argument("--repository")
        parser.add_argument("--global", action="store_true", dest="global")
        parser.add_argument("--text")
        parser.add_argument("--tag")
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--limit", type=int, default=100)
    elif path == "friction show":
        _add_show_options(parser)
    elif path in {"friction export", "friction import"}:
        _add_friction_transfer_options(parser, path)
    elif path == "friction add":
        parser.add_argument("--item", type=int)
        parser.add_argument("--source")
        parser.add_argument("--title")
        parser.add_argument("--global", action="store_true", dest="global")
        parser.add_argument("--target")
        parser.add_argument("--text")
        parser.add_argument("--tag", action="append", default=[])
    elif path == "friction set-status":
        parser.add_argument("--reason", required=True)
        parser.add_argument("id", type=int, nargs="+")
        parser.add_argument("status")
    elif path == "adopt record":
        parser.add_argument("--items", default="")
        parser.add_argument("--summary", required=True)
        parser.add_argument("--files", default="")
        parser.add_argument("--commit")
        parser.add_argument("--eval-before")
        parser.add_argument("--eval-after")
    elif path == "adopt recurrence":
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--limit", type=int, default=100)
    else:
        return {}
    try:
        parsed = vars(parser.parse_args(args))
    except (SystemExit, argparse.ArgumentError) as error:
        raise ValueError(str(error)) from error
    if path == "adopt record":
        parsed["items"] = [int(value) for value in parsed["items"].split(",") if value]
        parsed["files"] = [value for value in parsed["files"].split(",") if value]
    if (
        path == "friction export"
        and not parsed.get("md")
        and not parsed.get("directory")
    ):
        raise ValueError("provide a directory, or use --md [--out <file>]")
    return parsed


def _add_show_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id", nargs="+")
    parser.add_argument(
        "--brief", action="store_true", help="compact text output; ignores --json"
    )
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)


def _add_friction_transfer_options(parser: argparse.ArgumentParser, path: str) -> None:
    if path == "friction export":
        parser.add_argument("--md", action="store_true")
        parser.add_argument("--out", metavar="<FILE>")
        parser.add_argument("directory", nargs="?")
        return
    parser.add_argument("--repository")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("source")


def _write(io: object | None, value: str, *, error: bool = False) -> None:
    name = "stderr" if error else "stdout"
    stream = getattr(io, name, None) if io is not None else None
    if stream is None:
        stream = getattr(sys, name)
    stream.write(value)
