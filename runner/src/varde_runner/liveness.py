"""Pure helpers for runner liveness decisions."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

AGENT_OUTPUT_KINDS = frozenset(
    {"text", "tool_intent", "tool_result", "permission_requested"}
)
AGENT_OUTPUT_SESSION_END_STATUSES = frozenset({"completed", "interrupted"})


@dataclass(frozen=True)
class Liveness:
    state: str
    reason: str | None = None


def event_age_s(last_event_at: str | None, now: datetime) -> float | None:
    if last_event_at is None:
        return None
    timestamp = datetime.fromisoformat(last_event_at)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return max(0.0, (now - timestamp).total_seconds())


def derive_liveness(
    *,
    lifecycle: str,
    idle_status: str,
    last_event_age_s: float | None,
    process_alive: bool | None,
    pending_approvals: int,
    stall_after_s: float,
) -> Liveness:
    if lifecycle in {"completed", "archived"} or idle_status == "closed":
        return Liveness("closed")
    if lifecycle == "failed":
        return Liveness("error")
    if pending_approvals > 0:
        return Liveness("waiting")
    if idle_status == "idle":
        return Liveness("idle")
    if process_alive is False:
        return Liveness("stalled", "process_gone")
    if last_event_age_s is not None and last_event_age_s > stall_after_s:
        return Liveness("stalled", "silent")
    return Liveness("running")


def is_agent_output(kind: str, payload: Mapping[str, Any]) -> bool:
    if kind in AGENT_OUTPUT_KINDS:
        return True
    return (
        kind == "session_end"
        and payload.get("status") in AGENT_OUTPUT_SESSION_END_STATUSES
    )


def startup_phase(
    elapsed_s: float, warn_s: float, kill_s: float
) -> Literal["wait", "warn", "kill"]:
    if kill_s > 0 and elapsed_s >= kill_s:
        return "kill"
    if elapsed_s >= warn_s:
        return "warn"
    return "wait"
