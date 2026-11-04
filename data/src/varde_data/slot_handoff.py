"""Build deterministic plain-data slot handoff records."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from varde_data.records.queue import QueueItem, TaskState
from varde_data.slot_model import Slot, SlotEvent

RECENT_EVENT_LIMIT = 20


def build_handoff_record(
    slot: Slot,
    items: list[QueueItem],
    events: list[SlotEvent],
    task_states: list[TaskState],
    children: Sequence[Slot] = (),
    child_items: Sequence[QueueItem] = (),
) -> dict[str, Any]:
    """Build a stable checkpoint record from the current slot state.

    Orchestrator slots pass their same-plan child slots so the record carries
    each child and the items it holds; other slots pass nothing.
    """
    ordered_items = sorted(items, key=lambda item: (item.queue_name, item.id))
    ordered_events = sorted(events, key=lambda event: (event.seq, event.at))
    ordered_tasks = sorted(task_states, key=lambda task: (task.plan_dir, task.task_id))
    ordered_children = sorted(children, key=lambda child: child.slot_id)
    ordered_child_items = sorted(
        child_items, key=lambda item: (item.queue_name, item.id)
    )
    recent_events = ordered_events[-RECENT_EVENT_LIMIT:]

    return {
        "role": slot.role,
        "slot": asdict(slot),
        "plan_id": slot.plan_id,
        "epoch": slot.epoch,
        "claimed_items": [asdict(item) for item in ordered_items],
        "child_slots": [
            {
                "slot": asdict(child),
                "claimed_items": [
                    asdict(item)
                    for item in ordered_child_items
                    if item.claimed_by == child.slot_id
                ],
            }
            for child in ordered_children
        ],
        "last_progress": {
            "at": slot.last_progress_at,
            "note": slot.last_progress_note,
        },
        "context_tokens": slot.context_tokens,
        "recent_events": [asdict(event) for event in recent_events],
        "task_states": [asdict(task) for task in ordered_tasks],
        "next_actions": _next_actions(ordered_items),
    }


def _next_actions(items: list[QueueItem]) -> list[str]:
    if items:
        return [f"Continue or release claimed item {item.id}" for item in items]
    return ["Claim ready work or check the plan queue"]
