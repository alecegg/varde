"""Command line interface for ``varde learn sweep``."""

from __future__ import annotations

import json
import sys

from varde_core.envelope import success

from .help import help_text


def run(argv: list[str], io: object | None = None) -> int:
    args = list(argv)
    if args and args[0] == "sweep":
        args.pop(0)
    if "--help" in args or "-h" in args:
        stream = getattr(io, "stdout", sys.stdout) if io else sys.stdout
        stream.write(help_text("sweep"))
        return 0
    dry_run = "--dry-run" in args
    json_output = "--json" in args
    limit = None
    try:
        index = 0
        while index < len(args):
            if args[index] == "--limit":
                index += 1
                limit = int(args[index])
                if limit < 1:
                    _invalid_argument("--limit must be positive")
            elif args[index] not in {"--dry-run", "--json"}:
                _invalid_argument(f"unexpected argument '{args[index]}'")
            index += 1
        from .sweep.run import run_sweep

        result = run_sweep(dry_run=dry_run, limit=limit)
        stream = getattr(io, "stdout", sys.stdout) if io else sys.stdout
        if json_output:
            stream.write(
                json.dumps(success(result, {"truncated": False}), separators=(",", ":"))
                + "\n"
            )
        else:
            stream.write(
                f"Sweep: {result['analyzed']} analyzed, "
                f"{result['skipped']} skipped, "
                f"{result['friction_added']} friction added, "
                f"{len(result['failures'])} failures, "
                f"{len(result['warnings'])} warning"
                f"{'s' if len(result['warnings']) != 1 else ''}.\n"
            )
    except Exception as error:  # noqa: BLE001 - report CLI failures consistently
        stream = getattr(io, "stderr", sys.stderr) if io else sys.stderr
        stream.write(f"error: {error}\n")
        return 2
    else:
        return 0


def _invalid_argument(message: str) -> None:
    raise ValueError(message)
