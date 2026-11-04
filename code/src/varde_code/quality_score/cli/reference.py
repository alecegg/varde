"""``varde code quality reference build|show``: the repo's own reference scores."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from .. import reference as ref
from ..refactor_line import reference_line


def add_parsers(commands: Any) -> None:
    """Register ``build`` and ``show`` on a subparsers action."""
    build = commands.add_parser(
        "build", help="score the repo's own files and store the reference"
    )
    build.add_argument("--root", type=Path, default=Path.cwd())
    build.add_argument("--language", default="python")
    build.add_argument("--cap", type=int, default=ref.DEFAULT_CAP)
    build.add_argument(
        "--output",
        type=Path,
        help="reference JSON path (default .varde/quality/reference-<language>.json)",
    )
    show = commands.add_parser("show", help="print the stored or automatic reference")
    show.add_argument("--root", type=Path, default=Path.cwd())
    show.add_argument("--language", default="python")
    show.add_argument("--cap", type=int, default=ref.DEFAULT_CAP)
    show.add_argument("--reference", type=Path, help="stored reference JSON to read")


def summary(reference: ref.Reference) -> dict[str, Any]:
    """The reference with its p10 line; scores stay in the stored file."""
    shown = {key: value for key, value in reference.items() if key != "scores"}
    shown["p10"] = reference_line(reference["scores"])
    shown["confidence"] = ref.confidence(reference["n"])
    return shown


def run_build(args: argparse.Namespace, stdout: TextIO) -> int:
    root = args.root.resolve()
    reference = ref.build(root, args.language, args.cap)
    output = args.output or ref.default_path(root, args.language)
    ref.write(reference, output)
    print(json.dumps({"output": str(output), **summary(reference)}), file=stdout)
    return 0


def run_show(args: argparse.Namespace, stdout: TextIO) -> int:
    root = args.root.resolve()
    reference = ref.load_or_build(root, args.language, args.reference, args.cap)
    print(json.dumps(summary(reference), sort_keys=True), file=stdout)
    return 0


def run(args: argparse.Namespace, io: Any = None) -> int:
    stdout: TextIO = getattr(io, "stdout", sys.stdout)
    stderr: TextIO = getattr(io, "stderr", sys.stderr)
    try:
        if args.command == "build":
            return run_build(args, stdout)
        return run_show(args, stdout)
    except (OSError, ValueError) as exc:
        print(f"code quality reference: {exc}", file=stderr)
        return 2
