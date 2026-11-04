"""One-time migration of messages predating reader bindings."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data.messages import read_stray_messages, remove_stray_store
from varde_learn.knowledge.frontmatter import parse

from varde_workflow.inbox import (
    _repository,
    delivery_events,
    read_all,
    record_delivery,
    seed_reader_index,
)
from varde_workflow.legacy import plan_migration
from varde_workflow.msg_status import find_stray_stores


def _plan_statuses(working: Path) -> dict[str, str]:
    plans: dict[str, str] = {}
    root = working / "plans"
    if not root.exists():
        return plans
    for path in root.rglob("plan.md"):
        try:
            frontmatter, _ = parse(path.read_bytes())
        except OSError, ValueError:
            continue
        identifier = frontmatter.get("id", path.parent.name)
        status = frontmatter.get("status")
        if isinstance(identifier, str) and isinstance(status, str):
            plans[identifier] = status
    return plans


def run_migration(
    working: str | Path,
    *,
    now: datetime | None = None,
    plans: dict[str, str] | None = None,
) -> int:
    """Plan and persist migration records, preserving append-only stores."""
    working_path = Path(working)
    timestamp = now or datetime.now(UTC)
    existing = read_all(working_path)
    records = [message.to_dict() for message in existing]
    migration = plan_migration(
        records,
        delivery_events(working_path),
        _plan_statuses(working_path) if plans is None else plans,
        timestamp,
    )
    if not migration:
        return 0
    payload: dict[str, Any] = migration[0]
    seed_reader_index(working_path, "main")
    _repository(working_path).import_messages(payload["append"])
    for event in payload["marks"]:
        record_delivery(
            working_path,
            event["message_id"],
            event["reader"],
            event["event"],
            via="migration",
            now=event["at"],
        )
    return 0


def run(args: Any, working: str | Path) -> int:
    if args.strays:
        return migrate_strays(working, apply=args.apply)
    if args.apply:
        raise ValueError("--apply requires --strays")
    return run_migration(working)


def migrate_strays(working: str | Path, *, apply: bool = False) -> int:
    """Merge messages with unseen ids from discovered stray stores."""
    from varde_learn.knowledge.memory import find_root

    working_path = Path(working)
    root = find_root(Path.cwd())
    strays = find_stray_stores(root, working_path)
    seen = _repository(working_path).message_ids()
    additions: list[dict[str, Any]] = []
    skipped_by_stray: dict[Path, int] = {}
    for stray in strays:
        stray_messages, skipped = read_stray_messages(stray)
        skipped_by_stray[stray] = skipped
        for message in stray_messages:
            if message["id"] not in seen:
                additions.append(message)
                seen.add(message["id"])

    if apply and additions:
        _repository(working_path).import_messages(additions)
    kept_strays: list[Path] = []
    if apply:
        for stray in strays:
            if skipped_by_stray[stray]:
                kept_strays.append(stray)
                continue
            remove_stray_store(stray)
            if stray.exists():
                kept_strays.append(stray)
    action = "Merged" if apply else "Would merge"
    message_label = "message" if len(additions) == 1 else "messages"
    store_label = "store" if len(strays) == 1 else "stores"
    print(
        f"{action} {len(additions)} {message_label} from "
        f"{len(strays)} stray {store_label}."
    )
    skipped_total = sum(skipped_by_stray.values())
    if apply and skipped_total:
        print(
            f"Skipped {skipped_total} malformed or id-less lines; stray inboxes kept."
        )
    for stray in kept_strays:
        print(f"Kept stray store: {stray}")
    if not apply and strays:
        print(
            "Use --apply to merge and remove empty stray directories.", file=sys.stderr
        )
    return 0
