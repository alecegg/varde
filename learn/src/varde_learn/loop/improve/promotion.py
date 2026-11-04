"""Demand-driven promotion signal: steps whose how is requested or fails often.

Report-only. A promote candidate is a step whose how text should move into the
skill or its counted tool. The counting is `learn skills demand`; this module
only applies thresholds to that report.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Any

from varde_learn.loop import calls_retention, cli_how_report

PROMOTE_REQUESTS = 3
PROMOTE_TROUBLE = 2  # failed how requests plus friction items on the step


@dataclass(frozen=True)
class PromoteCandidate:
    step: str
    skill: str
    requests: int
    failures: int
    friction: int
    reasons: tuple[str, ...]


def promote_candidates(
    report: dict[str, Any],
    *,
    min_requests: int = PROMOTE_REQUESTS,
    min_trouble: int = PROMOTE_TROUBLE,
) -> list[PromoteCandidate]:
    """Steps over a threshold, most requested first (pure)."""
    found = []
    for row in report.get("steps", []):
        reasons = _reasons(row, min_requests, min_trouble)
        if reasons:
            skill = row["step"].split("/", 1)[0]
            found.append(
                PromoteCandidate(
                    row["step"],
                    skill,
                    row["requests"],
                    row["failures"],
                    row["friction"],
                    reasons,
                )
            )
    return sorted(found, key=lambda c: (-c.requests, c.step))


def _reasons(
    row: dict[str, Any], min_requests: int, min_trouble: int
) -> tuple[str, ...]:
    reasons = []
    if row["requests"] >= min_requests:
        reasons.append(f"requested {row['requests']} times")
    trouble = row["failures"] + row["friction"]
    if trouble >= min_trouble:
        reasons.append(f"{trouble} failures or friction items")
    return tuple(reasons)


def default_window(days: int | None) -> str | None:
    """The window for a loop read: the pruned days, or all rows when none are pruned."""
    return None if days is None else f"{days}d"


def read_demand_report(
    skill: str | None = None, window: str | None = None
) -> dict[str, Any]:
    """The `learn skills demand --json` data, read through its own command.

    Without a window the read covers the calls retention, not all time.
    """
    if window is None:
        window = default_window(calls_retention.window_exceeds_retention(None))
    args = ["--json"]
    if window:
        args += ["--window", window]
    if skill:
        args.append(skill)
    out = _Capture()
    code = cli_how_report.run(args, out)
    if code != 0:
        raise OSError(out.stderr.getvalue().strip() or "skills demand failed")
    return json.loads(out.stdout.getvalue())["data"]


class _Capture:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
