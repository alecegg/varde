"""CLI adapter for the pure handoff format validator."""

from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from varde_workflow.errors import report_failure_with_fix
from varde_workflow.handoff_format import validate
from varde_workflow.output import Fix, print_cli_success


def run(args: Any) -> int:
    path = Path(args.file)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"error: cannot read handoff file {path}: {error}", file=sys.stderr)
        return 2

    root = Path(args.repo_root)
    result = validate(text, lambda item: (root / item).exists())
    details = asdict(result)
    if args.json:
        if result.errors:
            return report_failure_with_fix(
                "handoff_invalid",
                1,
                "; ".join(result.errors),
                details,
                Fix.no_command("Correct the handoff sections and rerun handoff-check."),
                True,
            )
        print_cli_success(details)
    else:
        if result.errors:
            for error in result.errors:
                print(f"error: {error}", file=sys.stderr)
        else:
            print("Handoff format is valid.")
        for warning in result.warnings:
            print(f"warning: {warning}", file=sys.stderr)
    return 1 if result.errors else 0
