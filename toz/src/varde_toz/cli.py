"""Command line router. Command modules are imported only when selected."""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Sequence

TYPE_CHECKING = False  # avoid importing typing on the hook path
if TYPE_CHECKING:
    from varde_toz.doctor import DoctorSection


COMMANDS = (
    "query",
    "run",
    "capture",
    "index",
    "fetch",
    "stats",
    "purge",
    "migrate-metadata",
    "doctor",
    "profile",
    "event",
    "note",
    "hook",
)
MODULES = {name: name.replace("-", "_") for name in COMMANDS}
MODULES.update({"event": "event_note", "note": "event_note"})
_VALUE_GLOBALS = {"--fallback-dir": "TOZ_FALLBACK_DIR", "--project": "TOZ_PROJECT"}
_FLAG_GLOBALS = {"--json": "TOZ_JSON", "--quiet": "TOZ_QUIET"}


def _parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="varde-toz",
        description="Keep large tool output out of the LLM context window",
    )
    parser.add_argument("--fallback-dir")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("command", choices=COMMANDS, nargs="?")
    return parser


def _route(argv: Sequence[str]) -> tuple[dict[str, str | bool], str | None, list[str]]:
    """Consume recognized global options before the command and preserve its argv."""
    globals_found: dict[str, str | bool] = {}
    index = 0
    while index < len(argv):
        item = argv[index]
        if item in _VALUE_GLOBALS:
            if index + 1 == len(argv):
                return globals_found, None, list(argv[index:])
            globals_found[_VALUE_GLOBALS[item]] = argv[index + 1]
            index += 2
            continue
        if item in _FLAG_GLOBALS:
            globals_found[_FLAG_GLOBALS[item]] = True
            index += 1
            continue
        if item in ("-h", "--help"):
            return globals_found, None, list(argv[index:])
        return globals_found, item, list(argv[index + 1 :])
    return globals_found, None, []


def _apply_globals(global_values: dict[str, str | bool]) -> None:
    from .config import env_os

    for key, value in global_values.items():
        if key == "TOZ_FALLBACK_DIR" and env_os("TOZ_FALLBACK_DIR") is not None:
            continue
        os.environ[key] = "1" if value is True else str(value)


def main(
    argv: Sequence[str] | None = None, doctor_section: DoctorSection | None = None
) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    global_values, command, command_args = _route(raw_args)
    if command == "hook":
        return _dispatch_with_globals(
            global_values, command, command_args, doctor_section
        )

    parser = _parser()
    if command is None and (not raw_args or command_args in (["--help"], ["-h"])):
        parser.print_help()
        return 0
    if command is None or command not in MODULES:
        parser.error(f"unknown command: {command or raw_args[0]}")
    return _dispatch_with_globals(global_values, command, command_args, doctor_section)


def _dispatch_with_globals(
    global_values: dict[str, str | bool],
    command: str,
    command_args: list[str],
    doctor_section: DoctorSection | None = None,
) -> int:
    previous = {key: os.environ.get(key) for key in global_values}
    _apply_globals(global_values)
    try:
        return _dispatch(command, command_args, doctor_section)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _dispatch(
    command: str, argv: list[str], doctor_section: DoctorSection | None = None
) -> int:
    module_name = MODULES[command]
    try:
        module = importlib.import_module(f".commands.{module_name}", __package__)
    except ModuleNotFoundError as exc:
        if exc.name != f"{__package__}.commands.{module_name}":
            raise
        print(f"varde-toz: {command} is not implemented yet", file=sys.stderr)
        return 2
    handler = getattr(module, "main", None)
    if handler is None:
        print(f"varde-toz: {command} is not implemented yet", file=sys.stderr)
        return 2
    if command in ("event", "note"):
        return int(handler([command, *argv]) or 0)
    if command == "doctor" and doctor_section is not None:
        return int(handler(argv, doctor_section=doctor_section) or 0)
    return int(handler(argv) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
