"""Command-line entry point for the calibration tools."""

import argparse
import importlib
import sys
from collections.abc import Sequence

COMMANDS = (
    "init",
    "import",
    "label",
    "duel",
    "rate",
    "rank",
    "profile",
    "report",
    "verify",
    "export",
    "validate",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m varde_dev.calibrate",
        description="Calibrate quality score behavior.",
    )
    parser.add_argument("command", choices=COMMANDS, nargs="?")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    if args in ([], ["--help"], ["-h"]):
        parser.print_help()
        return 0

    namespace, remainder = parser.parse_known_args(args)
    if namespace.command is None:
        parser.error("a command is required")

    module_name = f"varde_dev.calibrate.{namespace.command}.commands"
    try:
        commands = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        group_package = f"varde_dev.calibrate.{namespace.command}"
        if error.name not in {module_name, group_package} and not error.name.startswith(
            f"{group_package}."
        ):
            raise
        print(
            f"calibrate {namespace.command}: not yet available",
            file=sys.stderr,
        )
        return 2

    return commands.main(remainder)
