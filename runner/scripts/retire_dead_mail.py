"""Compatibility wrapper for the installed `varde msg retire` workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "workflow" / "src"))

from varde_workflow import mail_retirement as retirement

AGE_LIMIT = retirement.AGE_LIMIT
terminal_plan_ids = retirement.terminal_plan_ids
address_plan_id = retirement.address_plan_id
eligible_address = retirement.eligible_address
build_dry_run = retirement.build_dry_run
write_dry_run = retirement.write_dry_run
apply_dry_run = retirement.apply_dry_run
restore = retirement.restore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--working", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", type=Path, metavar="AUDIT_DIR")
    action.add_argument("--apply", type=Path, metavar="DRY_RUN_FILE")
    action.add_argument("--restore", type=Path, metavar="AUDIT_FILE")
    args = parser.parse_args()
    if args.dry_run:
        retirement.write_dry_run(args.working, args.dry_run)
        return 0
    result = (
        retirement.apply_dry_run(args.working, args.apply)
        if args.apply
        else retirement.restore(args.working, args.restore)
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
