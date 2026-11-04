"""Pure plan-watch classification over caller-supplied facts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from varde_data.views.status import TASK_ACTIVE, TERMINAL, classify_status

APPROVED_MERGE_GRACE_SECONDS = 15 * 60

__all__ = [
    "APPROVED_MERGE_GRACE_SECONDS",
    "ActivityFacts",
    "WatchEvent",
    "WatchFacts",
    "WatchPlanState",
    "WatchTransitionFacts",
    "approved_merge_detail",
    "approved_merge_elapsed",
    "bound_branches",
    "frame_events",
    "idle_bucket",
    "is_waiting_line",
    "latest_activity",
    "owner_message_after",
    "plan_state",
    "task_counts",
    "waiting_is_live",
    "waiting_text",
    "watch_state_detail",
    "whole_plan_waiting_on_blocked",
]


@dataclass(frozen=True)
class ActivityFacts:
    """Activity timestamps collected by the workflow adapter."""

    newest_activity: float
    activity_source: str
    task_status_times: tuple[float, ...] = ()
    now_line_timestamp: float | None = None
    activity_candidates: tuple[tuple[float, str], ...] = ()


@dataclass(frozen=True)
class WatchFacts:
    """Plan status inputs collected by the workflow adapter."""

    now: float
    threshold: int
    newest_activity: float
    activity_source: str
    status: str = ""
    status_bucket: str = "other"
    tasks: tuple[dict[str, Any], ...] = ()
    done: int = 0
    blocked: tuple[str, ...] = ()
    questions: int = 0
    plan_age: int | None = None
    now_line: str | None = None
    waiting_live: bool = False


@dataclass(frozen=True)
class WatchTransitionFacts:
    state: str
    detail: str
    idle: int
    awaiting: bool
    approved_detail: str | None
    owner_message_after: bool
    stalled: str | None


@dataclass(frozen=True)
class WatchEvent:
    kind: str
    plan: str
    detail: str
    owner: str | None = None

    def line(self) -> str:
        label = (
            "idle-no-handback"
            if self.detail.startswith("idle-no-handback;")
            else self.kind
        )
        return f"{label} {self.plan} {self.detail}"

    def to_json(self) -> dict[str, str]:
        value = {"kind": self.kind, "plan": self.plan}
        if self.owner is not None:
            value["owner"] = self.owner
        value["detail"] = self.detail
        return value


@dataclass
class WatchPlanState:
    """In-memory cache record; its fields match the serialized cache shape."""

    state: str
    bucket: int = 0
    blocked: set[str] = field(default_factory=set)
    idle_no_handback: bool = False


def latest_activity(facts: ActivityFacts) -> tuple[float, str]:
    """Apply plan, task, now-line, commit, and worktree timestamp precedence."""
    latest, source = facts.newest_activity, facts.activity_source
    for timestamp in facts.task_status_times:
        if timestamp > latest:
            latest, source = timestamp, "task status"
    if facts.now_line_timestamp is not None and facts.now_line_timestamp >= latest:
        latest, source = facts.now_line_timestamp, "now line"
    for timestamp, candidate in facts.activity_candidates:
        if timestamp >= latest:
            latest, source = timestamp, candidate
    return latest, source


def idle_bucket(state: str, idle: int, threshold: int) -> int:
    """Return the event bucket for stale and merge-ready activity."""
    if state == "stale":
        return idle // max(1, threshold)
    if state == "merge-ready":
        return idle // (3 * max(1, threshold))
    return 0


def whole_plan_waiting_on_blocked(
    tasks: Iterable[Mapping[str, Any]],
    active: frozenset[str] = TASK_ACTIVE,
    terminal: frozenset[str] = TERMINAL,
) -> bool:
    task_list = list(tasks)
    if any(task["status"] in active for task in task_list):
        return False
    for task in task_list:
        if (
            task["status"] in terminal
            or task["status"] == "blocked"
            or task["status"] in active
        ):
            continue
        if all(
            all(
                candidate["status"] in terminal
                for candidate in task_list
                if candidate["stem"] == dependency or candidate["id"] == dependency
            )
            for dependency in task["depends"]
        ):
            return False
    return True


def task_counts(tasks: Iterable[Mapping[str, Any]]) -> tuple[int, int, list[str]]:
    """Count terminal tasks and return blocked task identifiers."""
    task_list = list(tasks)
    done = sum(classify_status(task["status"]) == "terminal" for task in task_list)
    blocked = [task["id"] for task in task_list if task["status"] == "blocked"]
    return done, len(task_list), blocked


def waiting_text(now_line: str | None) -> str:
    if now_line is not None and is_waiting_line(now_line):
        return now_line.removeprefix("waiting:").strip()
    return ""


def is_waiting_line(now_line: str | None) -> bool:
    return now_line is not None and now_line.startswith("waiting:")


def waiting_is_live(
    now: float, modified_times: Iterable[float], threshold: int
) -> bool:
    times = tuple(modified_times)
    return bool(times) and now - max(times) < 3 * max(1, threshold)


def plan_state(facts: WatchFacts) -> tuple[str | None, str, int]:
    """Classify a plan using gathered timestamps and task facts."""
    idle = max(0, int(facts.now - facts.newest_activity))
    if facts.status_bucket == "terminal":
        if facts.plan_age is None or facts.plan_age > max(1, facts.threshold):
            state, detail = None, ""
        else:
            state, detail = "finished", facts.status
    elif facts.questions:
        state, detail = "needs-decision", f"{facts.questions} open question(s)"
    elif facts.status == "blocked":
        state, detail = "blocked", "plan blocked"
    elif facts.tasks and facts.done == len(facts.tasks):
        state, detail = "merge-ready", f"{facts.done}/{len(facts.tasks)} tasks done"
    elif (
        facts.blocked
        and whole_plan_waiting_on_blocked(facts.tasks)
        and idle >= max(1, facts.threshold)
    ):
        state, detail = "blocked", "all tasks blocked"
    elif is_waiting_line(facts.now_line) and facts.waiting_live:
        state, detail = "waiting", ""
    elif idle >= max(1, facts.threshold):
        waiting = waiting_text(facts.now_line)
        detail = f"{idle // 60}m idle; last activity: {facts.activity_source}"
        if waiting:
            detail += f"; waiting: {waiting}"
        state = "stale"
    else:
        state, detail = "active", ""
    return state, detail, idle


def approved_merge_elapsed(approved: object, now: float) -> int | None:
    if not isinstance(approved, str):
        return None
    try:
        approved_at = datetime.fromisoformat(approved).timestamp()
    except ValueError:
        return None
    elapsed = max(0, int(now - approved_at))
    return elapsed if elapsed >= APPROVED_MERGE_GRACE_SECONDS else None


def approved_merge_detail(
    elapsed: int | None, branch_available: bool, merged: bool
) -> str | None:
    if elapsed is None or not branch_available or merged:
        return None
    return f"approved {elapsed // 60}m ago, not in main"


def owner_message_after(
    messages: Iterable[Mapping[str, Any]], plan_id: str, activity: float
) -> bool:
    cutoff = datetime.fromtimestamp(activity, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return any(
        message.get("from") == plan_id and message.get("ts", "") > cutoff
        for message in messages
    )


def watch_state_detail(facts: WatchTransitionFacts) -> tuple[str, str, bool]:
    """Apply awaiting, hand-back, approval, and stall state transitions."""
    if facts.awaiting:
        if facts.approved_detail:
            return "blocked", facts.approved_detail, False
        if facts.state == "stale":
            return "active", "", False
        return facts.state, facts.detail, False
    idle_no_handback = facts.state == "stale" and not facts.owner_message_after
    if idle_no_handback:
        detail = f"idle-no-handback; {facts.idle // 60}m idle without owner hand-back"
    else:
        detail = facts.detail
    blocked = (
        None
        if facts.state == "needs-decision"
        else facts.approved_detail or facts.stalled
    )
    if blocked:
        return "blocked", blocked, idle_no_handback
    return facts.state, detail, idle_no_handback


def bound_branches(
    record: Mapping[str, Any],
    tasks: Iterable[Mapping[str, Any]],
    all_ids: Iterable[str],
    branches: Iterable[str],
) -> list[str]:
    """Return branches bound to this plan, excluding longer plan ids."""
    plan_id = record["id"]
    prefix = f"worktree/{plan_id}-"
    longer_ids = [
        other
        for other in all_ids
        if other != plan_id and other.startswith(f"{plan_id}-")
    ]
    exact = {f"worktree/{plan_id}", *(f"worktree/{task['id']}" for task in tasks)}
    if record.get("branch"):
        exact.add(record["branch"])
    bound = []
    for name in branches:
        belongs_to_longer = any(
            name == f"worktree/{other}" or name.startswith(f"worktree/{other}-")
            for other in longer_ids
        )
        if not belongs_to_longer and (name in exact or name.startswith(prefix)):
            bound.append(name)
    return sorted(bound)


def frame_events(
    snapshot: Iterable[dict[str, Any]],
    now: float,
    threshold: int,
    previous: Mapping[str, Any],
    *,
    seed: bool = False,
) -> tuple[list[WatchEvent], dict[str, WatchPlanState]]:
    """Classify one snapshot and return its ordered events and next cache facts."""
    next_cache: dict[str, WatchPlanState] = {}
    plans = sorted(snapshot, key=lambda row: row["id"])
    if seed:
        for plan in plans:
            idle = max(0, int(now - plan["newest_activity"]))
            bucket = plan.get(
                "bucket", idle // max(1, threshold) if plan["state"] == "stale" else 0
            )
            next_cache[plan["id"]] = WatchPlanState(
                plan["state"],
                bucket,
                set(plan.get("blocked_tasks", [])),
                bool(plan.get("idle_no_handback", False)) and plan["state"] == "stale",
            )
        return [], next_cache
    events: list[WatchEvent] = []
    for plan in plans:
        plan_id, state = plan["id"], plan["state"]
        awaiting = bool(plan.get("awaiting_user"))
        idle = max(0, int(now - plan["newest_activity"]))
        bucket = plan.get(
            "bucket", idle // max(1, threshold) if state == "stale" else 0
        )
        blocked = set(plan.get("blocked_tasks", []))
        old = previous.get(plan_id)
        if state != "blocked" and not awaiting:
            events.extend(
                WatchEvent("blocked", plan_id, task, plan.get("owner"))
                for task in sorted(blocked - (old.blocked if old else set()))
            )
        changed = old is None or old.state != state or old.bucket != bucket
        idle_no_handback = (
            bool(plan.get("idle_no_handback", False)) and state == "stale"
        )
        if idle_no_handback and not awaiting and not (old and old.idle_no_handback):
            events.append(
                WatchEvent("stale", plan_id, plan["detail"], plan.get("owner"))
            )
        elif changed:
            kind = {
                "stale": "stale",
                "blocked": "blocked",
                "needs-decision": "needs-decision",
                "merge-ready": "merge-ready",
                "finished": "finished",
            }.get(state)
            if kind and not (awaiting and kind in {"stale", "blocked"}):
                events.append(
                    WatchEvent(
                        kind,
                        plan_id,
                        plan.get("detail", f"idle {idle}s"),
                        plan.get("owner"),
                    )
                )
        next_cache[plan_id] = WatchPlanState(state, bucket, blocked, idle_no_handback)
    return events, next_cache
