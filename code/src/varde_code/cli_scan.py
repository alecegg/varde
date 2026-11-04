"""CLI adapter for scan, scan setup, rule management, and rule tests."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path

from varde_code.query.output import render
from varde_code.query.params import QueryError
from varde_code.scan import report_run, rules_cmd, setup, test_cmd
from varde_code.scan.core import scan_repo

_HELP_FILES = {
    "": "scan_run.txt",
    "run": "scan_run.txt",
    "test": "scan_test.txt",
    "setup": "scan_setup.txt",
    "rules": "scan_rules.txt",
    "rules list": "scan_rules_list.txt",
    "rules diff": "scan_rules_diff.txt",
    "rules seed": "scan_rules_seed.txt",
    "rules remove": "scan_rules_remove.txt",
}


_SCAN_BOOL_FLAGS = {
    "--skip-quality": "skipQuality",
    "--migrate-preview": "migratePreview",
    "--allow-calibration-change": "allowCalibrationChange",
}
_SCAN_VALUE_FLAGS = {
    "--rules-ref": "rulesRef",
    "--changed-since": "changedSince",
    "--vs": "vs",
}
_FLAG_NAMES = {"--user", "--force", "--apply", *_SCAN_BOOL_FLAGS}


def help(path: str = "") -> str:
    """Return the committed Rust CLI help snapshot for a scan command."""
    filename = _HELP_FILES.get(path.strip())
    return (
        files("varde_code").joinpath("help", filename).read_text(encoding="utf-8")
        if filename
        else ""
    )


def run(argv: Sequence[str], io=None) -> int:
    """Run a routed scan command; argv may include its legacy command token."""
    args = list(argv)
    if args and args[0].startswith("varde"):
        args.pop(0)
    if not args:
        args = ["scan"]

    nested_scan = args[:2] == ["scan", "scan"]
    legacy = args[0] in {"scan", "test", "rules_list", "rules_seed", "rules_remove"}
    command = args.pop(0) if legacy else "scan"
    if (
        command == "scan"
        and args
        and args[0] in {"scan", "run", "setup", "test", "rules"}
    ):
        command = args.pop(0)
    if nested_scan and not args:
        return _missing_json("scan scan")
    if _help_requested(args):
        print(help(_help_path(command, args)), end="")
        return 0
    if "--report" in args:
        return _run_report(args)

    operation = {
        "rules_list": "list",
        "rules_seed": "seed",
        "rules_remove": "remove",
    }.get(command)
    if command == "rules":
        if not args:
            print(help("rules"), end="")
            return 0
        command, *args = args
        command = {
            "rules_list": "list",
            "rules_seed": "seed",
            "rules_remove": "remove",
        }.get(command, command)
        operation = command
    if command == "list" and "--user" in args:
        return _argument_error(
            "--user", "varde scan rules rules_list [OPTIONS] --json <JSON>"
        )
    if command == "diff":
        unexpected = next((arg for arg in args if arg != "--json"), None)
        if unexpected is not None:
            return _argument_error(
                unexpected, "varde scan rules rules_list [OPTIONS] --json <JSON>"
            )
        return _argument_error(
            "--json", "varde scan rules rules_list [OPTIONS] --json <JSON>"
        )

    json_input, flags, values = _arguments(args)
    if json_input is None:
        return _missing_json(command)
    try:
        input_value = _require_object(json.loads(json_input))
        if input_value.get("operation") in {"list", "diff", "seed", "remove"}:
            operation = input_value["operation"]
        if command in {"scan", "run"}:
            if input_value.get("operation") == "setup":
                input_value["scope"] = (
                    "user" if "--user" in flags else input_value.get("scope", "repo")
                )
                input_value["force"] = "--force" in flags or input_value.get(
                    "force", False
                )
                result = setup.run(input_value)
                _print_scan_result(result)
                return 0
            if "--apply" in flags:
                input_value["apply"] = True
            if "--force" in flags:
                input_value["force"] = True
            for flag, key in _SCAN_BOOL_FLAGS.items():
                if flag in flags:
                    input_value[key] = True
            for flag, key in _SCAN_VALUE_FLAGS.items():
                if flag in values:
                    input_value[key] = values[flag]
            result = scan_repo(input_value, capture=io.capture if io else None)
            code = 0 if result.get("gate", {}).get("status") == "pass" else 1
        elif command == "setup":
            input_value["scope"] = (
                "user" if "--user" in flags else input_value.get("scope", "repo")
            )
            input_value["force"] = "--force" in flags or input_value.get("force", False)
            result = setup.run(input_value)
            code = 0
        elif command == "test":
            result = test_cmd.run_tests(input_value, capture=io.capture if io else None)
            code = 1 if result.get("summary", {}).get("failed", 0) else 0
        elif operation in {"list", "diff", "seed", "remove"}:
            input_value["operation"] = operation
            result = rules_cmd.run(
                operation,
                input_value,
                user="--user" in flags,
                force="--force" in flags,
            )
            code = 0
        else:
            return _unknown(command)
        if command == "setup" or operation in {"list", "diff", "seed", "remove"}:
            _print_scan_result(result)
        else:
            print(json.dumps(render(result, input_value), separators=(",", ":")))
    except (ValueError, TypeError, QueryError) as error:
        message = (
            "input is not valid JSON: EOF while parsing an object at line 1 column 1"
            if json_input == "{"
            else str(error)
        )
        wrapped = {
            "data": {
                "error": {
                    "code": getattr(error, "code", "invalid_input"),
                    "message": message,
                }
            },
            "meta": {"compact": False, "truncated": False},
            "ok": False,
            "outcome": "tool-error",
            "schema_version": 1,
        }
        print(json.dumps(wrapped, separators=(",", ":")))
        rules_operation = operation in {
            "list",
            "diff",
            "seed",
            "remove",
        } or command in {
            "rules",
            "rules_list",
            "rules_seed",
            "rules_remove",
            "list",
            "diff",
            "seed",
            "remove",
        }
        return 0 if rules_operation else 1
    else:
        return code


def _run_report(args: list[str]) -> int:
    """Parse the ``--report`` flags and run the scan report."""
    root = None
    max_behind = 100
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"--repo-root", "--readme-max-behind"} and index + 1 < len(args):
            value = args[index + 1]
            if arg == "--repo-root":
                root = Path(value)
            elif value.isdigit():
                max_behind = int(value)
            else:
                return _argument_error(value, "varde scan --report [OPTIONS]")
            index += 2
            continue
        if arg not in {"--report", "--no-build", "-v", "--verbose"}:
            return _argument_error(arg, "varde scan --report [OPTIONS]")
        index += 1
    return report_run.run_report(
        root or report_run.default_root(), "--no-build" in args, max_behind
    )


def _require_object(value: object) -> dict:
    if not isinstance(value, dict):
        raise QueryError("invalid_input", "input must be a JSON object")
    return value


def _print_scan_result(result: dict) -> None:
    """Print setup and rules results in the standard response envelope."""
    envelope = {
        "data": result,
        "meta": {"compact": True, "truncated": False},
        "ok": True,
        "outcome": "success",
        "schema_version": 1,
    }
    print(
        json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )


def _arguments(args: list[str]) -> tuple[str | None, list[str], dict[str, str]]:
    value = None
    flags = []
    values: dict[str, str] = {}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--json" and index + 1 < len(args):
            value = args[index + 1]
            index += 2
            continue
        if arg in _FLAG_NAMES:
            flags.append(arg)
            index += 1
            continue
        if arg in _SCAN_VALUE_FLAGS and index + 1 < len(args):
            values[arg] = args[index + 1]
            index += 2
            continue
        if arg in {"-v", "--verbose"}:
            index += 1
            continue
        if arg == "--rule-id" and index + 1 < len(args):
            index += 1
        index += 1
    return value, flags, values


def _help_requested(args: list[str]) -> bool:
    return any(arg in {"--help", "-h"} for arg in args)


def _help_path(command: str, args: list[str]) -> str:
    if command == "rules" and args and args[0] in {"list", "diff", "seed", "remove"}:
        return "rules " + args[0]
    if args and args[0] in {"setup", "test"}:
        return args[0]
    if command in {"scan", "run"}:
        return "run"
    if command == "rules_list":
        return "rules list"
    if command == "rules_seed":
        return "rules seed"
    if command == "rules_remove":
        return "rules remove"
    if command in {"list", "seed", "remove"}:
        return f"rules {command}"
    if command == "diff":
        return "rules diff"
    return command


def _unknown(command: str) -> int:
    print(f"error: unrecognized subcommand '{command}'", file=sys.stderr)
    return 2


def _argument_error(argument: str, usage: str) -> int:
    print(
        f"error: unexpected argument '{argument}' found\n\n"
        f"Usage: {usage}\n\nFor more information, try '--help'.",
        file=sys.stderr,
    )
    return 2


def _missing_json(command: str) -> int:
    if command == "scan scan":
        usage = "varde scan scan --json <JSON>"
    else:
        usage = (
            "varde scan --json <JSON>"
            if command in {"scan", "run"}
            else f"varde scan {command} --json <JSON>"
        )
    print(
        "error: the following required arguments were not provided:\n"
        "  --json <JSON>\n\n"
        f"Usage: {usage}\n\nFor more information, try '--help'.",
        file=sys.stderr,
    )
    return 2
