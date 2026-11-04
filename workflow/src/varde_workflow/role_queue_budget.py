"""Pure resource budget checks for role queue starts."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeGuard

QUEUE_BUDGET_SECTION = "queue_budget"
DEFAULT_GLOBAL_WORKER_CEILING = 24
DEFAULT_RSS_MB_MAX = 1_000_000.0
DEFAULT_CPU_PCT_MAX = 100_000.0
DEFAULT_PROCESSES_MAX = 100_000


@dataclass(frozen=True)
class ResourceSnapshot:
    taken_at: datetime
    providers: dict[str, float]
    rss_mb: float
    cpu_pct: float
    processes: int
    live_workers: int


@dataclass(frozen=True)
class BudgetLimits:
    provider_max: dict[str, float]
    rss_mb_max: float
    cpu_pct_max: float
    processes_max: int
    global_worker_ceiling: int


DEFAULT_LIMITS = BudgetLimits(
    provider_max={},
    rss_mb_max=DEFAULT_RSS_MB_MAX,
    cpu_pct_max=DEFAULT_CPU_PCT_MAX,
    processes_max=DEFAULT_PROCESSES_MAX,
    global_worker_ceiling=DEFAULT_GLOBAL_WORKER_CEILING,
)


@dataclass(frozen=True)
class Decision:
    ok: bool
    reason: str


def may_start(
    snapshot: ResourceSnapshot | None,
    limits: BudgetLimits,
    now: datetime,
) -> Decision:
    if snapshot is None:
        return Decision(False, "resource snapshot missing")
    if now - snapshot.taken_at > timedelta(seconds=60):
        return Decision(False, "resource snapshot stale")

    for provider, maximum in limits.provider_max.items():
        usage = snapshot.providers.get(provider)
        if usage is not None and usage > maximum:
            return Decision(False, f"provider_max[{provider}]")
    if snapshot.rss_mb > limits.rss_mb_max:
        return Decision(False, "rss_mb_max")
    if snapshot.cpu_pct > limits.cpu_pct_max:
        return Decision(False, "cpu_pct_max")
    if snapshot.processes > limits.processes_max:
        return Decision(False, "processes_max")
    if snapshot.live_workers >= limits.global_worker_ceiling:
        return Decision(False, "global_worker_ceiling")
    return Decision(True, "within budget")


def runner_toml_path() -> Path:
    """Resolve the runner config the CLI shares with the runner endpoint."""
    configured = os.environ.get("VARDE_RUNNER_CONFIG_DIR")
    directory = Path(configured) if configured else Path.home() / ".config" / "varde"
    return directory / "runner.toml"


def load_limits(path: Path) -> tuple[BudgetLimits | None, str]:
    """Read the one `[queue_budget]` table shared by the CLI and the endpoint.

    A missing file or table yields `DEFAULT_LIMITS`. An unreadable file, bad
    TOML, or an invalid table yields `None` and a reason naming the key.
    """
    try:
        with path.open("rb") as source:
            document = tomllib.load(source)
    except FileNotFoundError:
        return DEFAULT_LIMITS, ""
    except OSError:
        return None, f"budget config invalid: {path} unreadable"
    except tomllib.TOMLDecodeError:
        return None, f"budget config invalid: {path} is not valid TOML"
    table = document.get(QUEUE_BUDGET_SECTION)
    if table is None:
        return DEFAULT_LIMITS, ""
    if not isinstance(table, dict):
        return _invalid(QUEUE_BUDGET_SECTION)
    return _limits_from_table(table)


def _limits_from_table(table: dict[str, Any]) -> tuple[BudgetLimits | None, str]:
    provider_max = table.get("provider_max", {})
    if not isinstance(provider_max, dict) or not all(
        isinstance(name, str) and _is_number(value)
        for name, value in provider_max.items()
    ):
        return _invalid("queue_budget.provider_max")
    rss_mb_max = table.get("rss_mb_max")
    if not _is_number(rss_mb_max):
        return _invalid("queue_budget.rss_mb_max")
    cpu_pct_max = table.get("cpu_pct_max")
    if not _is_number(cpu_pct_max):
        return _invalid("queue_budget.cpu_pct_max")
    processes_max = table.get("processes_max")
    if not _is_int(processes_max):
        return _invalid("queue_budget.processes_max")
    global_worker_ceiling = table.get("global_worker_ceiling")
    if not _is_int(global_worker_ceiling):
        return _invalid("queue_budget.global_worker_ceiling")
    return (
        BudgetLimits(
            provider_max={name: float(value) for name, value in provider_max.items()},
            rss_mb_max=float(rss_mb_max),
            cpu_pct_max=float(cpu_pct_max),
            processes_max=processes_max,
            global_worker_ceiling=global_worker_ceiling,
        ),
        "",
    )


def _invalid(key: str) -> tuple[None, str]:
    return None, f"budget config invalid: {key}"


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)
