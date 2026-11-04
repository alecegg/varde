"""Definitions for runner's built-in scheduled jobs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JobSpec:
    key: str
    title: str
    spends_model_usage: bool
    default_enabled: bool
    default_time: str
    run_budget_usd: float | None = None
    run_budget_tokens: int | None = None


def effective_enabled(spec: JobSpec, stored_enabled: bool | None = None) -> bool:
    """Return stored enablement or the safe registry default."""
    if stored_enabled is not None:
        return stored_enabled
    return spec.default_enabled and not spec.spends_model_usage


BUILTIN_JOBS = (
    JobSpec("sweep", "Session sweep", False, True, "03:00"),
    JobSpec("soak", "Mail soak", False, True, "03:15"),
    JobSpec(
        "review", "Daily learn review", True, False, "04:00", run_budget_tokens=100_000
    ),
)

JOBS_BY_KEY = {job.key: job for job in BUILTIN_JOBS}
