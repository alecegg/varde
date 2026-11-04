"""Explicitly retire message addresses without changing inbox contents."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def run(args, working: str | Path) -> int:
    """Run the reviewed dry-run, apply, or restore retirement operation."""
    from varde_workflow import mail_retirement

    dry_run = getattr(args, "dry_run", None)
    apply_file = getattr(args, "apply", None)
    restore_file = getattr(args, "restore", None)
    addresses = getattr(args, "addresses", [])
    selected = [dry_run, apply_file, restore_file]
    if any(value is not None for value in selected):
        if sum(value is not None for value in selected) != 1 or addresses:
            print("Error: choose exactly one retirement operation", file=sys.stderr)
            return 1
        try:
            if dry_run is not None:
                mail_retirement.write_dry_run(
                    Path(working), dry_run, getattr(args, "min_age_days", 30)
                )
                return 0
            if apply_file is not None:
                result = mail_retirement.apply_dry_run(Path(working), apply_file)
            elif restore_file is not None:
                result = mail_retirement.restore(Path(working), restore_file)
            else:
                print("Error: missing retirement file", file=sys.stderr)
                return 1
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    print("Error: explicit addresses are not supported; use --dry-run", file=sys.stderr)
    return 1
