"""CLI for pull-based role queues."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from varde_data.errors import DataError, Invalid
from varde_data.queue import open_queue, open_slots
from varde_data.queue_paths import queue_migration_pending
from varde_data.queue_store import QUEUE_MIGRATION_COMMAND
from varde_data.queue_store import status as queue_store_status
from varde_data.records.queue import QueueItem, QueueItemInput
from varde_data.repos.queue import QueueRepository
from varde_data.slot_model import Slot
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.errors import InternalError, report_error
from varde_workflow.output import print_cli_success
from varde_workflow.queue_telemetry import queue_telemetry
from varde_workflow.role_pull import (
    finish,
    pull,
    release,
    renew,
)
from varde_workflow.role_queue_budget import (
    BudgetLimits,
    Decision,
    ResourceSnapshot,
    load_limits,
    may_start,
    runner_toml_path,
)
from varde_workflow.role_queue_flow import FOLLOWUP_CAP, follow_up_cap_reached
from varde_workflow.role_queue_independence import readiness
from varde_workflow.role_queue_metrics import lane_metrics

_SNAPSHOT = Path(".cache/data/resources.json")


def _budget(
    snapshot: ResourceSnapshot | None, now: datetime
) -> tuple[BudgetLimits | None, Decision]:
    limits, reason = load_limits(runner_toml_path())
    if limits is None:
        return None, Decision(False, reason)
    return limits, may_start(snapshot, limits, now)


def _snapshot(working: Path) -> ResourceSnapshot | None:
    path = working / _SNAPSHOT
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return ResourceSnapshot(
        taken_at=datetime.fromisoformat(value["taken_at"]),
        providers={
            key: float(amount) for key, amount in value.get("providers", {}).items()
        },
        rss_mb=float(value["rss_mb"]),
        cpu_pct=float(value["cpu_pct"]),
        processes=int(value["processes"]),
        live_workers=int(value["live_workers"]),
    )


def _item_data(item: QueueItem) -> dict[str, Any]:
    return asdict(item)


def _blocked_reason(
    item: QueueItem,
    in_flight: list[QueueItem],
    unmerged_dependencies: set[str],
) -> str:
    return readiness(
        item, in_flight, unmerged_dependencies=unmerged_dependencies
    ).reason


def _status(repo: QueueRepository, working: Path, queue_name: str) -> dict[str, Any]:
    items = repo.list(queue_name=queue_name)
    events = [event for item in items for event in repo.events(item.id)]
    active = [
        item for item in items if item.state in {"claimed", "building", "in_review"}
    ]
    states = {item.id: item.state for item in items}
    snapshot = _snapshot(working)
    limits, budget = _budget(snapshot, datetime.now(UTC))
    ceiling = limits.global_worker_ceiling if limits else 0
    roles: dict[str, dict[str, Any]] = {}
    for role in sorted({item.role or "unassigned" for item in items}):
        role_items = [item for item in items if (item.role or "unassigned") == role]
        readiness = {
            item.id: _blocked_reason(
                item,
                active,
                {
                    dependency
                    for dependency in item.depends_on
                    if states.get(dependency) != "merged"
                },
            )
            for item in role_items
            if item.state == "queued"
        }
        for item in role_items:
            if item.state != "queued":
                continue
            if any(dependency not in states for dependency in item.depends_on):
                readiness[item.id] = "waiting-on-unwritten"
        ready_count = sum(reason == "independent" for reason in readiness.values())
        blocked = [
            {"item_id": item_id, "reason": reason}
            for item_id, reason in readiness.items()
            if reason != "independent"
        ]
        roles[role] = {
            "queued": sum(item.state == "queued" for item in role_items),
            "claimed": sum(
                item.state in {"claimed", "building", "in_review"}
                for item in role_items
            ),
            "ready": ready_count if budget.ok else 0,
            "blocked_by": blocked,
        }
    telemetry = queue_telemetry(
        items,
        events,
        self_count=sum(item.role in {None, "coordinator"} for item in items),
        builder_count=sum(item.role == "builder" for item in items),
        orchestrator_count=sum(item.role == "orchestrator" for item in items),
        delegated_count=len(items)
        - sum(item.role in {None, "coordinator"} for item in items),
    )
    return {
        "roles": roles,
        "budget": {
            "ok": budget.ok,
            "reason": budget.reason,
            "free": max(
                0,
                ceiling - (snapshot.live_workers if snapshot else ceiling),
            ),
        },
        "items": [_item_data(item) for item in items],
        "telemetry": asdict(telemetry),
    }


def _metrics(repo: QueueRepository, queue_name: str) -> dict[str, Any]:
    items = repo.list(queue_name=queue_name)
    events = [event for item in items for event in repo.events(item.id)]
    return asdict(lane_metrics(items, events, datetime.now(UTC)))


def _run(  # noqa: PLR0911 - one response branch per queue action.
    args: Any, working: Path
) -> dict[str, Any]:
    action = args.queue_action
    queue_name = getattr(args, "queue", "roles/global")
    if action == "status" and queue_migration_pending(working):
        return queue_store_status(working) | {
            "message": f"queue migration pending: run {QUEUE_MIGRATION_COMMAND}"
        }
    repo = open_queue(working)
    slots = open_slots(working)
    if action == "pull":
        snapshot = _snapshot(working)
        limits, budget = _budget(snapshot, datetime.now(UTC))
        if limits is None:
            return {"item": None, "reason": budget.reason}
        result = pull(
            repo,
            slots,
            queue_name=queue_name,
            role=args.role,
            slot_id=args.slot,
            epoch=args.epoch,
            lease_s=1200,
            snapshot=snapshot,
            limits=limits,
            now=datetime.now(UTC),
        )
        return {
            "item": _item_data(result.item) if result.item else None,
            "reason": result.reason,
        }
    if action == "renew":
        slot = cast("Slot", renew(slots, slot_id=args.slot, epoch=args.epoch))
        return {"slot": asdict(slot)}
    if action == "finish":
        item = repo.get(queue_name, args.item)
        capped = follow_up_cap_reached(item, args.outcome)
        next_item = finish(
            slots, item, slot_id=args.slot, epoch=args.epoch, outcome=args.outcome
        )
        next_items = next_item
        return {
            "finished": args.item,
            "follow_up": _item_data(next_items[0]) if next_items else None,
            "follow_ups": [_item_data(follow_up) for follow_up in next_items],
            "follow_up_result": (
                "cap-reached" if capped else "enqueued" if next_items else "none"
            ),
        }
    if action == "release":
        released = release(
            slots,
            queue_name=queue_name,
            item_id=args.item,
            slot_id=args.slot,
            epoch=args.epoch,
        )
        return {"item": _item_data(released)}
    if action == "status":
        return _status(repo, working, queue_name)
    if action == "metrics":
        return _metrics(repo, queue_name)
    if action == "enqueue":
        plan_dir = str(Path(args.plan_dir).expanduser().resolve())
        parent_id = getattr(args, "parent", None)
        followup_depth = 0
        if parent_id:
            parent = repo.get(queue_name, parent_id)
            followup_depth = parent.followup_depth + 1
            if followup_depth > FOLLOWUP_CAP:
                raise Invalid(
                    f"cap-reached: follow-up depth {followup_depth} exceeds "
                    f"queue follow-up cap {FOLLOWUP_CAP}"
                )
        item = repo.enqueue(
            QueueItemInput(
                id=args.id,
                plan_dir=plan_dir,
                owned_files="\n".join(args.owned_file),
                depends_on=tuple(args.depends_on),
                serialize_with=tuple(args.serialize_with),
                role=args.role,
                queue_name=queue_name,
                extra={
                    "kind": args.kind,
                    "inputs": {"route_tier": route}
                    if (route := getattr(args, "route", None))
                    else {},
                },
                followup_depth=followup_depth,
            )
        )
        return {"item": _item_data(item)}
    raise ValueError(f"unknown queue action: {action}")


def run(args: Any) -> int:
    """Execute one role queue operation."""
    working = MemoryPaths.resolve(Path.cwd()).working.path
    try:
        result = _run(args, working)
    except (DataError, OSError, ValueError, KeyError, TypeError) as error:
        return report_error(
            InternalError(str(error)), bool(getattr(args, "json", False))
        )
    if args.json:
        print_cli_success(result)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
