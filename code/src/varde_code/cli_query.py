"""CLI adapter for the ``varde map`` query commands."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from typing import cast

from varde_core.io import Io

from varde_code import OutputCapture

from .query import dispatch
from .query.nav_map import nav_map_text
from .query.output import render

# Import each handler module so its register_mode calls run before dispatch.
for _module_name in ("find_pattern", "graph", "mapping", "simple"):
    import_module(f".query.{_module_name}", __package__)

HELP_DIR = Path(__file__).with_name("help")


def _capture(io: Io | None) -> OutputCapture | None:
    if io is None or io.capture is None:
        return None
    return cast("OutputCapture", io.capture)


_MODE_HELP = {
    "batch": "map_batch.txt",
    "symbols_in_file": "map_symbols_in_file.txt",
    "symbols_in_files": "map_symbols_in_files.txt",
    "get_symbol": "map_get_symbol.txt",
    "dependencies": "map_dependencies.txt",
    "dependents": "map_dependents.txt",
    "tests_for_file": "map_tests_for_file.txt",
    "hotspots": "map_hotspots.txt",
    "clusters": "map_clusters.txt",
    "map_file": "map_map_file.txt",
    "map_symbol": "map_map_symbol.txt",
    "map_path": "map_map_path.txt",
    "explore": "map_explore.txt",
    "blast_radius": "map_blast_radius.txt",
    "symbol_blast_radius": "map_symbol_blast_radius.txt",
    "detect_changes": "map_detect_changes.txt",
    "find_imports": "map_find_imports.txt",
    "type_hierarchy": "map_type_hierarchy.txt",
    "filter_symbols": "map_filter_symbols.txt",
    "find_pattern": "map_find_pattern.txt",
    "context_pack": "map_context_pack.txt",
    "nav_map": "map_nav_map.txt",
    "slice_state": "map_slice_state.txt",
}


def help_text(*path: str) -> str:
    """Return the checked-in help snapshot for the requested map path."""
    if not path or path == ("map",):
        filename = "map.txt"
    elif path[0] == "map" and len(path) == 2:
        filename = _MODE_HELP.get(path[1])
    elif len(path) == 1:
        filename = _MODE_HELP.get(path[0])
    else:
        filename = None
    if filename is None:
        return ""
    return (HELP_DIR / filename).read_text(encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="varde map", add_help=False)
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="mode")
    for mode in _MODE_HELP:
        command = commands.add_parser(mode, add_help=False)
        command.add_argument("-v", "--verbose", action="store_true")
        command.add_argument("--json", required=True)
        if mode == "nav_map":
            command.add_argument("--format", choices=("json", "text"), default="json")
            command.add_argument("--with-project-knowledge", action="store_true")
    return parser


def _plain_envelope(value):
    if isinstance(value, dict):
        return {
            key: _plain_envelope(item)
            for key, item in value.items()
            if key != "envelope_version"
        }
    if isinstance(value, list):
        return [_plain_envelope(item) for item in value]
    return value


def run(argv: Sequence[str], io: Io | None = None) -> int:
    """Run one map command; ``argv`` excludes the ``map`` token."""
    args = list(argv)
    if args and args[0] == "map":
        args.pop(0)
    if not args or args in (["--help"], ["-h"]):
        print(help_text("map"), end="")
        return 0
    if len(args) >= 2 and args[1] in {"--help", "-h"}:
        print(help_text("map", args[0]), end="")
        return 0

    command = next((arg for arg in args if not arg.startswith("-")), None)
    if command is not None and command not in _MODE_HELP:
        print(
            f"error: unrecognized subcommand '{command}'\n\n"
            "Usage: varde map [OPTIONS] <COMMAND>\n\n"
            "For more information, try '--help'.",
            file=sys.stderr,
        )
        return 2

    parsed = _parser().parse_args(args)
    if parsed.mode is None:
        print(help_text("map"), end="")
        return 0
    value: object = None
    try:
        value = json.loads(parsed.json)
    except ValueError, TypeError:
        result = render(
            None,
            error=(
                "invalid_input",
                (
                    "input is not valid JSON: EOF while parsing an object at line 1 "
                    "column 1"
                ),
            ),
        )
    else:
        if isinstance(value, dict) and isinstance(value.get("repoRoot"), str):
            from varde_code.index.paths import repo_db_path

            value.setdefault("dbPath", str(repo_db_path(Path(value["repoRoot"]))))
        result = dispatch(parsed.mode, value, capture=_capture(io))
    if parsed.mode == "nav_map" and parsed.format == "text" and result.get("ok"):
        output = nav_map_text(
            {**result, **(value if isinstance(value, dict) else {})},
            parsed.with_project_knowledge,
        )
    else:
        output = json.dumps(
            _plain_envelope(result),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    print(output)
    return 0


def help(path: str = "") -> str:
    """Module help hook for the app's ``varde map`` route."""
    parts = tuple(part for part in path.split(" ") if part)
    return help_text(*parts)


__all__ = ["HELP_DIR", "help", "help_text", "run"]
