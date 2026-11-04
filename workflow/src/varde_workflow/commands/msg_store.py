"""CLI for append-only message store transfer and verification."""

from __future__ import annotations

import sys
from pathlib import Path

from varde_data.errors import DataError
from varde_data.messages_transfer import export, repair_mode, transfer, verify
from varde_data.store_mode import read_store_mode, set_store_mode


def run(args, working: str | Path) -> int:
    working = Path(working)
    try:
        if args.store_action == "mode":
            print(set_store_mode(working, args.mode))
            return 0
        if args.store_action == "import":
            report = transfer(working, args.from_store, args.to_store, importing=True)
        elif args.store_action == "sync":
            report = transfer(working, args.from_store, args.to_store)
        elif args.store_action == "export":
            report = export(working, Path(args.dest))
        else:
            if args.repair_mode:
                print(repair_mode(working, force_adopt=args.force_adopt))
                if read_store_mode(working) is None:
                    print(
                        "Error: store mode repair did not produce a valid marker",
                        file=sys.stderr,
                    )
                    return 1
                return 0
            report = verify(working, args.from_store, args.to_store)
    except (DataError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(
        f"messages {report.source_messages}->{report.target_messages}; "
        f"skipped={report.skipped}; torn-tail={report.torn_tail}; "
        "checks=message-ids,message-sequences,reply-to,delivery-events,ack-history,"
        "reader-positions,unread-per-reader,concluded-addresses; "
        "snapshot=best-effort (rerun after concurrent writes)"
    )
    for mismatch in report.mismatches:
        print(f"mismatch: {mismatch}", file=sys.stderr)
    return 0 if report.ok else 1
