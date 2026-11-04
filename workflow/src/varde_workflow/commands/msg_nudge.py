"""Record main-agent nudges."""

from __future__ import annotations

import sys
from pathlib import Path

from varde_workflow.nudges import append


def run(args, working: str | Path) -> int:
    """Append a nudge record without sending an inbox message."""
    try:
        record = append(working, args.to, args.reason)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Recorded nudge for {record['address']} ({record['reason']})")
    return 0
