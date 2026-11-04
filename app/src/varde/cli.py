"""Console entry point and command dispatch."""

from __future__ import annotations

import os
import re
import signal
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from varde_core.module import Module

from .help.snapshots import ROOT_HELP, VERSION


def _resolve(path: Sequence[str]):
    from .router import resolve

    return resolve(path)


def _help_path(argv: list[str]) -> tuple[str, ...] | None:
    help_form = bool(argv and argv[0] == "help")
    words = argv[1:] if help_form else argv
    if help_form:
        words = [*words, "--help"]
    if not words or words[-1] not in ("--help", "-h"):
        return None
    path = words[:-1]
    resolved = _resolve(path)
    if resolved is None:
        return None
    route, _ = resolved
    route_help = len(path) == len(route.path)
    if route_help:
        return tuple(path)
    return None


def _module_for_help(
    path: tuple[str, ...], modules: dict[str, Module]
) -> Module | None:
    result = _resolve(path)
    if result is None:
        return next(iter(modules.values()), None)
    route, _ = result
    return modules.get(route.module)


def _discover_modules() -> dict[str, Module]:
    from .discovery import discover_modules

    return discover_modules()


def _create_io():
    from .io import create_io

    return create_io()


def _write_help(path: tuple[str, ...], modules: dict[str, Module]) -> int:
    from .help.route_snapshots import ROUTE_HELP

    snapshot = ROUTE_HELP.get(path)
    if snapshot is not None:
        sys.stdout.write(snapshot)
        return 0
    module = _module_for_help(path, modules)
    if module is None:
        print("varde: no command modules are installed", file=sys.stderr)
        return 2
    text = module.help(" ".join(path))
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def _write_denied(argv: list[str]) -> int | None:
    from .router import denied_route

    denied = denied_route(argv)
    if denied is None:
        return None
    route, word = denied
    from .help.route_snapshots import ROUTE_HELP

    help_text = ROUTE_HELP.get(route.path, "")
    usage = next(
        (line for line in help_text.splitlines() if line.startswith("Usage: ")), None
    )
    if usage is None:
        return None
    print(
        f"error: unrecognized subcommand '{word}'\n\n{usage}\n\n"
        "For more information, try '--help'.",
        file=sys.stderr,
    )
    return 2


def _write_unknown(argv: list[str]) -> int:
    word = argv[0]
    print(
        f"error: unrecognized subcommand '{word}'\n\n"
        "Usage: varde [OPTIONS] <COMMAND>\n\nFor more information, try '--help'.",
        file=sys.stderr,
    )
    return 2


def _write_group_help(args: list[str]) -> int | None:
    path = tuple(args)
    explicit_help = bool(path and path[-1] in ("--help", "-h"))
    if explicit_help:
        path = path[:-1]
    if path not in {("setup",), ("scan", "rules")}:
        return None
    from .help.route_snapshots import ROUTE_HELP

    stream = sys.stdout if explicit_help else sys.stderr
    stream.write(ROUTE_HELP[path])
    return 0 if explicit_help else 2


def _ignore_broken_pipe() -> int:
    with suppress(OSError):
        sys.stdout.close()
        sys.stdout = open(os.devnull, "w")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run Varde and return its process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    started = monotonic()
    status = 1
    command: list[str | None] = []
    try:
        try:
            status = _run_main(args, command)
        except SystemExit as error:
            status = (
                error.code
                if isinstance(error.code, int)
                else 0
                if error.code is None
                else 1
            )
            raise
        return status
    finally:
        if command != [None]:
            resolved_command = command[0] if command else _fallback_command(args)
            _record_call(
                resolved_command or _fallback_command(args),
                started,
                status,
                arg=_how_topic_arg(args),
            )


def _fallback_command(args: list[str]) -> str:
    if (
        not args
        or args[0] == "help"
        or any(value in ("--help", "-h") for value in args)
    ):
        return "help"
    if args in (["--version"], ["-V"]):
        return "version"
    return "unknown"


_HOW_TOPIC = re.compile(r"[a-z0-9-]+/[a-z0-9-]+")


def _how_topic_arg(args: list[str]) -> str | None:
    """Return `<skill>/<step>` for a `learn how` call, or None if not a valid topic."""
    if args[:2] != ["learn", "how"]:
        return None
    operands = [value for value in args[2:] if value[:1] != "-"]
    if len(operands) != 2:
        return None
    topic = "/".join(operands)
    return topic if _HOW_TOPIC.fullmatch(topic) else None


def _record_call(
    command: str, started: float, status: int, arg: str | None = None
) -> None:
    try:
        from datetime import UTC, datetime

        from varde_learn.loop.calls import (
            FAILURE,
            SUCCESS,
            CallRow,
            append_call,
            session_id,
        )

        row: CallRow = {
            "ts": datetime.now(UTC).isoformat(),
            "command": command,
            "status": SUCCESS if status == 0 else FAILURE,
            "duration_s": max(0.0, monotonic() - started),
            "session": session_id(),
        }
        if arg is not None:
            row["arg"] = arg
        append_call(row)
    except Exception:  # noqa: BLE001, S110 - telemetry must not affect CLI behavior.
        pass


def _mark_fastpath(command: list[str | None] | None) -> None:
    if command is not None:
        command.append(None)


def _help_subcommands(help_text: str) -> set[str]:
    """Return command names listed by a route's help tree."""
    names: set[str] = set()
    in_commands = False
    for line in help_text.splitlines():
        if line in {"Commands:", "Subcommands:"}:
            in_commands = True
            continue
        if in_commands and (not line or not line[0].isspace()):
            in_commands = False
        if in_commands:
            name = line.strip().split("  ", maxsplit=1)[0] if line.strip() else ""
            if "[" in name or "<" in name:
                name = name.split(maxsplit=1)[0]
            if name:
                names.add(name)
    return names


def _try_help(module_help: Callable[[str], str] | None, words: list[str]) -> str | None:
    if module_help is None:
        return None
    try:
        return module_help(" ".join(words))
    except Exception:  # noqa: BLE001 - recording must not affect CLI behavior
        return None


def _recorded_route(
    path: tuple[str, ...],
    args: list[str],
    help_text: str,
    module_help: Callable[[str], str] | None = None,
) -> str:
    """Name a route and its longest validated command chain."""
    command = list(path)
    current_help = help_text
    index = len(path)
    while index < len(args):
        children = _help_subcommands(current_help)
        child = next(
            (
                name
                for name in sorted(children, key=len, reverse=True)
                if args[index : index + len(name.split())] == name.split()
            ),
            None,
        )
        if child is not None:
            command.extend(child.split())
            index += len(child.split())
        elif module_help is not None:
            candidate = [*command, args[index]]
            candidate_help = _try_help(module_help, candidate)
            if candidate_help is None:
                break
            usage = next(
                (
                    line
                    for line in candidate_help.splitlines()
                    if line.startswith("Usage: ")
                ),
                "",
            )
            if " ".join(candidate) not in usage:
                break
            command.append(args[index])
            index += 1
        else:
            break
        current_help = _try_help(module_help, command)
        if current_help is None:
            break
    return " ".join(command)


def _setup_help() -> str:
    from .help.route_snapshots import ROUTE_HELP

    return ROUTE_HELP.get(("setup",), "")


def _run_setup(args: list[str], command: list[str | None] | None) -> int | None:
    from .setup.dispatch import run_setup_route

    _skip_guardrail_fire_recording(args, command)
    _skip_poller_recording(args, command)
    result = run_setup_route(args)
    if result is not None and command is not None and command != [None]:
        command.append(_recorded_route(("setup",), args, _setup_help()))
    return result


def _name_unresolved_setup(args: list[str], command: list[str | None] | None) -> None:
    if command is not None and command != [None] and args[:1] == ["setup"]:
        command.append(_recorded_route(("setup",), args, _setup_help()))


def _skip_guardrail_fire_recording(
    args: list[str], command: list[str | None] | None
) -> None:
    if args[:3] == ["learn", "sessions", "fire"]:
        _mark_fastpath(command)


def _skip_poller_recording(args: list[str], command: list[str | None] | None) -> None:
    if args[:2] in (["setup", "watch"], ["plan", "watch"]):
        _mark_fastpath(command)


def _run_main(args: list[str], command: list[str | None] | None = None) -> int:
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    if args in (["--version"], ["-V"]):
        sys.stdout.write(VERSION)
        return 0
    if not args or args in (["--help"], ["-h"], ["help"]):
        try:
            sys.stdout.write(ROOT_HELP)
        except BrokenPipeError:
            return _ignore_broken_pipe()
        return 0
    try:
        group_help = _write_group_help(args)
        if group_help is not None:
            return group_help
        help_path = _help_path(args)
        if args[0] == "__worker":
            return _write_unknown(args)
        if help_path is not None:
            if not help_path:
                sys.stdout.write(ROOT_HELP)
                return 0
            from .help.route_snapshots import ROUTE_HELP

            snapshot = ROUTE_HELP.get(help_path)
            if snapshot is not None:
                sys.stdout.write(snapshot)
                return 0

        from .fastpath import run as run_fastpath

        fast_result = run_fastpath(args)
        if fast_result is not None:
            _mark_fastpath(command)
            return fast_result

        setup_result = _run_setup(args, command)
        if setup_result is not None:
            return setup_result

        denied = _write_denied(args)
        if denied is not None:
            return denied

        modules = _discover_modules()
        if help_path is not None:
            return _write_help(help_path, modules)
        resolved = _resolve(args)
        if resolved is None:
            _name_unresolved_setup(args, command)
            return _write_unknown(args)
        route, forwarded = resolved
        module = modules.get(route.module)
        if command is not None and command != [None]:
            module_help = getattr(module, "help", None)
            help_text = _try_help(module_help, list(route.path)) or ""
            command.append(_recorded_route(route.path, args, help_text, module_help))
        if route.path == ("setup", "doctor"):
            from varde_toz.cli import main as toz_main

            from .setup.hooks_install.doctor import doctor_section

            return toz_main(forwarded[1:], doctor_section=doctor_section())
        if route.path == ("run",):
            from varde_toz.cli import main as toz_main

            return toz_main(forwarded[1:])
        if module is None:
            print(
                f"varde: command module {route.module!r} is not installed",
                file=sys.stderr,
            )
            return 2
        return int(module.run(forwarded, _create_io()))
    except BrokenPipeError:
        return _ignore_broken_pipe()
