"""Route-decision records and summaries for orchestration telemetry."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

RouteTier = Literal["self", "builder", "orchestrator"]


@dataclass(frozen=True)
class RouteDecision:
    """One measured routing choice and its eventual quality outcomes."""

    route_tier: RouteTier
    reviewers: tuple[str, ...] | None
    model: str | None
    provider: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost: float | None
    review_verdict: str | None = None
    pyright_errors: int | None = None
    baseline_failures: int | None = None
    retries: int | None = None
    review_findings: int | None = None
    task_id: str | None = None


@dataclass(frozen=True)
class RouteTierSummary:
    """Aggregated volume and cost for a routing tier."""

    decisions: int
    input_tokens: int
    output_tokens: int
    cost: float
    retries: int
    review_findings: int


@dataclass(frozen=True)
class RouteDecisionRead:
    decisions: tuple[RouteDecision, ...]
    corrupt_lines: int


def append_route_decision(path: Path, decision: RouteDecision) -> None:
    """Append one JSON record, creating the notes directory when needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(asdict(decision), sort_keys=True) + "\n")


def read_route_decisions(path: Path) -> RouteDecisionRead:
    """Read valid route decisions and count corrupt JSONL records."""
    if not path.exists():
        return RouteDecisionRead((), 0)
    decisions: list[RouteDecision] = []
    corrupt_lines = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    corrupt_lines += 1
                    continue
                row["route_tier"] = parse_route_tier(row.get("route_tier"))
                fields = RouteDecision.__dataclass_fields__
                row = {key: value for key, value in row.items() if key in fields}
                if row.get("reviewers") is not None:
                    row["reviewers"] = tuple(row["reviewers"])
                decisions.append(RouteDecision(**row))
            except AttributeError, KeyError, TypeError, ValueError:
                corrupt_lines += 1
                continue
    return RouteDecisionRead(tuple(decisions), corrupt_lines)


def summarize_route_decisions(
    decisions: Iterable[RouteDecision],
) -> dict[RouteTier, RouteTierSummary]:
    """Group records by route tier and total decision volume and cost."""
    totals: dict[RouteTier, list[int | float]] = defaultdict(
        lambda: [0, 0, 0, 0.0, 0, 0]
    )
    for decision in decisions:
        total = totals[decision.route_tier]
        total[0] += 1
        total[1] += decision.input_tokens or 0
        total[2] += decision.output_tokens or 0
        total[3] += decision.cost or 0.0
        total[4] += decision.retries or 0
        total[5] += decision.review_findings or 0
    return {
        tier: RouteTierSummary(
            int(total[0]),
            int(total[1]),
            int(total[2]),
            float(total[3]),
            int(total[4]),
            int(total[5]),
        )
        for tier, total in totals.items()
    }


def parse_route_tier(value: object) -> RouteTier:
    legacy = {"direct": "self", "plan": "orchestrator", "orchestrate": "orchestrator"}
    if value in legacy:
        return legacy[value]  # type: ignore[return-value]
    if value in {"self", "builder", "orchestrator"}:
        return value  # type: ignore[return-value]
    raise ValueError("unknown route tier")
