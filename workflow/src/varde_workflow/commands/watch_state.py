"""Build a generated-block model from classified watch plans."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from varde_workflow.commands.watch_block import BlockModel, PlanRow, PlanState


def model(plans: list[dict[str, Any]]) -> BlockModel:
    rows = []
    blocked = []
    for plan in plans:
        state = plan["state"]
        stale_since = (
            datetime.fromtimestamp(plan["newest_activity"], UTC).strftime("%H:%M")
            if state == "stale"
            else None
        )
        rows.append(
            PlanRow(
                plan["id"],
                PlanState(state, stale_since),
                plan.get("done", 0),
                plan.get("total", 0),
                len(plan.get("blocked_tasks", [])),
                plan.get("open_questions", 0),
                plan.get("now_line"),
                plan.get("idle_no_handback", False),
            )
        )
        blocked.extend(f"{plan['id']}/{task}" for task in plan.get("blocked_tasks", []))
    return BlockModel(rows, blocked)
