"""Pure follow-up item construction for role queues."""

from __future__ import annotations

from typing import cast

from varde_data.records.queue import QueueItem, QueueItemInput

FOLLOWUP_CAP = 3
REVIEWER_ROLES = frozenset(
    {
        "varde-reviewer",
        "reviewer",
        "spec-adherence",
        "readability",
        "ux-advocate",
        "accessibility",
    }
)


def follow_up(done: QueueItem, outcome: str) -> tuple[QueueItemInput, ...]:
    """Build the builder fix item when a reviewer finishes with findings."""
    if done.followup_depth >= FOLLOWUP_CAP:
        return ()
    if done.role not in REVIEWER_ROLES:
        return ()
    if outcome == "findings":
        return (_next_item(done, role="builder", kind="fix", suffix="fix"),)
    return ()


def follow_up_cap_reached(done: QueueItem, outcome: str) -> bool:
    """Return whether this completion would create a follow-up past the cap."""
    would_follow_up = done.role in REVIEWER_ROLES and outcome == "findings"
    return would_follow_up and done.followup_depth >= FOLLOWUP_CAP


def _next_item(done: QueueItem, *, role: str, kind: str, suffix: str) -> QueueItemInput:
    extra = dict(done.extra or {})
    raw_inputs = extra.get("inputs")
    inputs = (
        cast("dict[str, object]", raw_inputs) if isinstance(raw_inputs, dict) else {}
    )
    extra["inputs"] = inputs
    extra["kind"] = kind
    return QueueItemInput(
        id=f"{done.id}-{suffix}",
        plan_dir=done.plan_dir,
        owned_files=done.owned_files,
        depends_on=done.depends_on,
        serialize_with=done.serialize_with,
        role=role,
        queue_name=done.queue_name,
        extra=extra,
        followup_depth=done.followup_depth + 1,
    )
