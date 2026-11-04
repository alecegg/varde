"""Pure governor rules for the manager bot: caps, daily budget, loop detection.

No I/O. The caller passes audit rows, session rows and the clock; each check
returns None when the call may proceed, or a ``Breach`` naming what stopped it.
"""

from __future__ import annotations

import json
import tomllib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from varde_data.records.bot import AuditRow

from varde_runner.bot_profile import BOT_ROLE
from varde_runner.bot_taint import is_bot_rooted

DEAD_LIFECYCLES = frozenset({"completed", "archived"})
LOOP_REPEAT = (3, timedelta(minutes=10))
LOOP_CYCLES = (2, timedelta(minutes=30))
LOOP_REFUSALS = (20, timedelta(minutes=5))
BUDGET_WARN_FRACTION = 0.8
STOP_ACTIONS = frozenset({"agent_stop", "agent_archive"})


@dataclass(frozen=True, slots=True)
class Caps:
    max_concurrent_agents: int = 4
    max_launches_per_hour: int = 6
    daily_token_budget: int = 5_000_000
    max_actions_per_minute: int = 30
    hourly_token_estimate: int = 250_000
    stop_agents_on_stop: bool = True


@dataclass(frozen=True, slots=True)
class Breach:
    status: int
    reason: str
    pause: bool = False
    stop_agents: bool = False


@dataclass(frozen=True, slots=True)
class Usage:
    """Live and finished bot-rooted session figures the caps are checked against."""

    bot_live: int
    all_live: int
    max_live_instances: int
    tokens_today: int


def load_caps(path: Path) -> Caps:
    """Read ``[bot]`` caps from runner.toml; a bad or missing value is the default."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8")).get("bot", {})
    except OSError, tomllib.TOMLDecodeError:
        return Caps()
    defaults = Caps()
    values: dict[str, Any] = {}
    for name in (
        "max_concurrent_agents",
        "max_launches_per_hour",
        "daily_token_budget",
        "max_actions_per_minute",
        "hourly_token_estimate",
    ):
        value = data.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            values[name] = value
    stop = data.get("stop_agents_on_stop")
    values["stop_agents_on_stop"] = (
        stop if isinstance(stop, bool) else defaults.stop_agents_on_stop
    )
    return Caps(**values)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _is_live(row: Mapping[str, Any]) -> bool:
    return row.get("lifecycle") not in DEAD_LIFECYCLES


def bot_rooted(sessions: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Sessions launched by the bot plus every descendant (by `parent_id`)."""
    rooted = {
        row["id"]
        for row in sessions
        if is_bot_rooted(row.get("launched_by")) or row.get("role") == BOT_ROLE
    }
    grew = True
    while grew:
        grew = False
        for row in sessions:
            parent = row.get("parent_id")
            if row["id"] not in rooted and parent in rooted:
                rooted.add(row["id"])
                grew = True
    return [row for row in sessions if row["id"] in rooted]


def reported_tokens(payloads: Iterable[Mapping[str, Any]]) -> int | None:
    """Largest cumulative token count reported by usage events, or None if none."""
    best: int | None = None
    for payload in payloads:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            continue
        total = usage.get("total")
        counts = total if isinstance(total, dict) else usage
        value = counts.get("total_tokens")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            best = max(best or 0, value)
    return best


def session_tokens_today(
    started_at: datetime,
    ended_at: datetime | None,
    reported: int | None,
    now: datetime,
    hourly_estimate: int,
) -> int:
    """Reported tokens, or the hourly estimate for hours run since UTC midnight."""
    if reported is not None:
        return reported
    midnight = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = max(started_at, midnight)
    end = min(ended_at or now, now)
    hours = max((end - start).total_seconds(), 0) / 3600
    return round(hours * hourly_estimate)


def _recent(rows: Iterable[AuditRow], now: datetime, window: timedelta):
    cutoff = now - window
    return [row for row in rows if parse_ts(row.ts) >= cutoff]


def _calls(rows: Iterable[AuditRow]) -> list[AuditRow]:
    return sorted((r for r in rows if r.phase == "call"), key=lambda r: r.id)


def _is_write(row: AuditRow) -> bool:
    return row.status != "read" and row.action != "permission"


def count_launches(rows: Iterable[AuditRow], now: datetime) -> int:
    window = _recent(rows, now, timedelta(hours=1))
    return sum(
        r.phase == "call" and r.action == "launch" and r.status == "allowed"
        for r in window
    )


def count_actions(rows: Iterable[AuditRow], now: datetime) -> int:
    window = _recent(rows, now, timedelta(minutes=1))
    return sum(
        r.phase == "call" and r.status == "allowed" and r.action != "permission"
        for r in window
    )


def check_caps(
    caps: Caps,
    action: str,
    usage: Usage,
    rows: Sequence[AuditRow],
    now: datetime,
    reserved: int = 0,
) -> Breach | None:
    """Budget first (it always pauses), then instances, concurrency, rates."""
    if usage.tokens_today >= caps.daily_token_budget:
        return Breach(
            423,
            f"cap daily_token_budget ({caps.daily_token_budget}) reached",
            pause=True,
            stop_agents=caps.stop_agents_on_stop,
        )
    if action == "launch":
        if usage.all_live + reserved >= usage.max_live_instances:
            return Breach(429, f"cap max_live_instances ({usage.max_live_instances})")
        if usage.bot_live + reserved >= caps.max_concurrent_agents:
            return Breach(
                429, f"cap max_concurrent_agents ({caps.max_concurrent_agents})"
            )
        if count_launches(rows, now) >= caps.max_launches_per_hour:
            return Breach(
                429, f"cap max_launches_per_hour ({caps.max_launches_per_hour})"
            )
    if count_actions(rows, now) >= caps.max_actions_per_minute:
        return Breach(
            429, f"cap max_actions_per_minute ({caps.max_actions_per_minute})"
        )
    return None


def budget_warning(caps: Caps, usage: Usage) -> bool:
    return usage.tokens_today >= caps.daily_token_budget * BUDGET_WARN_FRACTION


def detect_loop(rows: Sequence[AuditRow], now: datetime) -> str | None:
    """Reason for a loop pause, or None. Reads and permission-free repeats ignored."""
    return (
        _repeated_action(rows, now)
        or _launch_stop_cycles(rows, now)
        or _many_refusals(rows, now)
    )


def _repeated_action(rows: Sequence[AuditRow], now: datetime) -> str | None:
    count, window = LOOP_REPEAT
    recent = [r for r in _calls(_recent(rows, now, window)) if _is_write(r)]
    seen = Counter((r.action, r.args_digest) for r in recent)
    for (action, _), n in seen.items():
        if n >= count:
            return f"loop: {action} repeated {n} times in 10 minutes"
    return None


def _launch_plan(row: AuditRow) -> str | None:
    if row.plan_id:
        return row.plan_id
    try:
        address = json.loads(row.redacted_args).get("address")
    except ValueError, AttributeError:
        return None
    plan = address.get("plan") if isinstance(address, dict) else None
    return plan if isinstance(plan, str) else None


def _launch_stop_cycles(rows: Sequence[AuditRow], now: datetime) -> str | None:
    """Count stops of agents the bot launched, per plan.

    A launch is known by its `result` row (it carries the created agent id); a
    stop counts once, when it targets such an agent.
    """
    count, window = LOOP_CYCLES
    cycles: Counter[str] = Counter()
    launched: dict[str, str] = {}
    for row in sorted(_recent(rows, now, window), key=lambda r: r.id):
        if row.phase == "result" and row.action == "launch" and row.status == "ok":
            plan = _launch_plan(row)
            if row.agent_id and plan:
                launched[row.agent_id] = plan
        elif (
            row.phase == "call"
            and row.status == "allowed"
            and row.action in STOP_ACTIONS
            and row.agent_id in launched
        ):
            cycles[launched.pop(row.agent_id)] += 1
    for plan, n in cycles.items():
        if n >= count:
            return f"loop: {n} launch and stop cycles on plan {plan} in 30 minutes"
    return None


def _many_refusals(rows: Sequence[AuditRow], now: datetime) -> str | None:
    count, window = LOOP_REFUSALS
    refused = sum(
        r.phase == "call" and r.status == "denied" for r in _recent(rows, now, window)
    )
    if refused >= count:
        return f"loop: {refused} refused calls in 5 minutes"
    return None
