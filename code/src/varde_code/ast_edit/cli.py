"""CLI adapter for ``varde edit preview|apply``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from varde_core import envelope
from varde_core.io import Io

from .apply import apply
from .preview import RewriteRule, preview


@dataclass(frozen=True)
class Options:
    repository_root: Path
    store_dir: Path


def cli_command():
    """Return an argparse command tree for the app's edit route."""
    parser = argparse.ArgumentParser(
        prog="varde edit", description="Preview and apply AST edits"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    preview_parser = commands.add_parser(
        "preview", help="Build a rewrite proposal without changing source files"
    )
    source = preview_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--rules", type=Path)
    source.add_argument("--language")
    preview_parser.add_argument("--pattern")
    preview_parser.add_argument("--replacement")
    preview_parser.add_argument("--path", type=Path, action="append", required=True)
    preview_parser.add_argument("--out", type=Path)
    preview_parser.add_argument("--json", action="store_true")
    apply_parser = commands.add_parser(
        "apply", help="Apply a saved proposal after validating its source snapshots"
    )
    apply_parser.add_argument("--proposal", type=Path, required=True)
    apply_parser.add_argument("--json", action="store_true")
    return parser


def run(argv: Sequence[str], io: Io | None, options: Options) -> int:
    """Run the edit command. ``argv`` may include ``varde edit`` tokens."""
    del io
    args = list(argv)
    while args and args[0] in {"varde", "edit"}:
        args.pop(0)
    if args and args[0] in {"preview", "apply"}:
        command = args[0]
        if any(arg in {"--help", "-h"} for arg in args[1:]):
            from importlib.resources import files

            filename = "edit_preview.txt" if command == "preview" else "edit_apply.txt"
            help_text = (
                files("varde_code")
                .joinpath("help", filename)
                .read_text(encoding="utf-8")
            )
            print(help_text, end="")
            return 0
        unexpected = _unexpected_argument(args[1:])
        if unexpected is not None:
            usage = (
                "varde edit preview [OPTIONS] --path <PATH> "
                "<--rules <FILE>|--language <LANGUAGE>>"
                if command == "preview"
                else "varde edit apply [OPTIONS] --proposal <FILE>"
            )
            print(
                f"error: unexpected argument '{unexpected}' found\n\n"
                f"Usage: {usage}\n\nFor more information, try '--help'.",
                file=sys.stderr,
            )
            return 2
    parser = cli_command()
    try:
        parsed = parser.parse_args(args)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 0
    if parsed.command == "preview":
        if parsed.rules is not None:
            try:
                rules = [
                    RewriteRule(**value)
                    for value in json.loads(parsed.rules.read_text(encoding="utf-8"))
                ]
            except (OSError, ValueError, TypeError) as error:
                return _error("invalid_rules", str(error), parsed.json)
        else:
            if not parsed.pattern or not parsed.replacement:
                return _error(
                    "invalid_rules",
                    "--language requires --pattern and --replacement",
                    parsed.json,
                )
            rules = [
                RewriteRule(
                    "cli-rule", parsed.language, parsed.pattern, parsed.replacement
                )
            ]
        result = preview(
            options.repository_root,
            Path.cwd(),
            parsed.path,
            parsed.out or options.store_dir,
            rules,
        )
        data = {
            "complete": result.complete,
            "applicable": result.applicable,
            "proposal_id": result.proposal.get("id") if result.proposal else None,
            "files": [
                {"path": item["path"], "replacement_count": item["replacement_count"]}
                for item in result.proposal["files"]
            ]
            if result.proposal
            else [],
            "diagnostics": [item.__dict__ for item in result.diagnostics],
            "proposal_path": str(result.proposal_path)
            if result.proposal_path
            else None,
            "diff_path": str(result.diff_path) if result.diff_path else None,
        }
        if parsed.json:
            value = (
                envelope.success(data, {"truncated": False})
                if result.complete
                else envelope.negative_result(
                    "preview_incomplete",
                    _first_error(result.diagnostics),
                    data,
                    {"truncated": False},
                )
            )
            print(json.dumps(value, separators=(",", ":")))
        else:
            if result.diff:
                print(result.diff, end="")
            elif result.complete:
                print("varde edit: no applicable edits")
            for item in result.diagnostics:
                print(
                    f"varde edit: {'error' if item.blocking else 'warning'}: "
                    f"{item.code}: {item.message}",
                    file=sys.stderr,
                )
            if result.proposal_path:
                print(f"Proposal: {result.proposal_path}")
        return 0 if result.complete else 1
    try:
        proposal = json.loads(parsed.proposal.read_text(encoding="utf-8"))
        result = apply(proposal, options.repository_root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        return _error(
            "invalid_proposal" if not parsed.proposal.exists() else "apply_failed",
            str(error),
            parsed.json,
        )
    ok = all(item["status"] == "applied" for item in result["files"])
    if parsed.json:
        data = {"proposal_id": result["proposal_id"], "files": result["files"]}
        value = (
            envelope.success(data, {"truncated": False})
            if ok
            else envelope.negative_result(
                "apply_incomplete",
                next(
                    (
                        item["path"] + ": " + str(item["detail"])
                        for item in result["files"]
                        if item["detail"]
                    ),
                    "apply incomplete",
                ),
                data,
                {"truncated": False},
            )
        )
        print(json.dumps(value, separators=(",", ":")))
    else:
        for item in result["files"]:
            if item["status"] == "applied":
                print(f"Applied {item['path']}")
            else:
                print(f"varde edit: {item['path']}: {item['detail']}", file=sys.stderr)
    return 0 if ok else 1


def _first_error(diagnostics) -> str:
    item = next((diagnostic for diagnostic in diagnostics if diagnostic.blocking), None)
    return f"{item.code}: {item.message}" if item else "preview is incomplete"


def _unexpected_argument(args: list[str]) -> str | None:
    value_options = {
        "--rules",
        "--language",
        "--pattern",
        "--replacement",
        "--path",
        "--out",
        "--proposal",
    }
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in value_options:
            index += 2
            continue
        if not arg.startswith("-"):
            return arg
        index += 1
    return None


def _error(code: str, message: str, json_output: bool) -> int:
    if json_output:
        print(json.dumps(envelope.tool_error(code, message), separators=(",", ":")))
    else:
        print(f"varde edit: {message}", file=sys.stderr)
    return 1
