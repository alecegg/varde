"""Pure functions for the deterministic delta-verdict evaluation (no I/O).

Two verdicts are compared for a variant of a file:

- worse than before: the variant scores below the same file unmodified;
- below the reference p10: the variant scores below the 10th percentile of the
  repo's own file scores, with the file itself left out (leave-one-out).

Comparing a degradation with its own unmodified file is partly circular: any
degradation that moves the score is a drop, and an unchanged file is never
worse than itself. Only the leave-one-out reference comparison and the mined
before -> after pairs carry information about detection and false positives.
"""

from __future__ import annotations

import math
import random
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from varde_code.quality_score.refactor_line import needs_refactor, reference_line

DEV = "dev"
STABILITY_SIZES = (10, 20, 50)
STABILITY_DRAWS = 200
TOLERANCES = (0.0, 0.5, 1.0, 2.0, 3.0, 5.0)
TOLERANCE_FP_TARGET = 0.10


class SplitError(ValueError):
    """An item outside the dev split was asked for."""


def require_dev(item_id: str, split_of: Callable[[str], str]) -> None:
    split = split_of(item_id)
    if split != DEV:
        raise SplitError(f"{item_id} is in the {split} split; only dev is readable")


def leave_one_out(scores: Sequence[float], index: int) -> list[float]:
    """The reference without the file at ``index``, so it is not self-judged."""
    return [s for i, s in enumerate(scores) if i != index]


def worse_than_before(after: float, before: float, tolerance: float = 0.0) -> bool:
    return before - after > tolerance


def below_p10(score: float, reference: Sequence[float]) -> bool:
    return needs_refactor(score, reference_line(reference))


def rate(hits: int, n: int) -> dict[str, Any]:
    return {"hits": hits, "n": n, "rate": None if n == 0 else hits / n}


def fmt(cell: Mapping[str, Any]) -> str:
    """``12% (3/25, n=25)``; every rate line carries its n."""
    if cell["rate"] is None:
        return f"- (n={cell['n']})"
    return f"{100 * cell['rate']:.0f}% ({cell['hits']}/{cell['n']}, n={cell['n']})"


def tally(flags: Sequence[bool]) -> dict[str, Any]:
    return rate(sum(flags), len(flags))


def quantile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank quantile (``q`` in 0..1); None without values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(q * len(ordered)), 1) - 1]


def distribution(values: Sequence[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "min": min(values, default=None),
        "p10": quantile(values, 0.10),
        "p25": quantile(values, 0.25),
        "median": quantile(values, 0.50),
        "p75": quantile(values, 0.75),
        "p90": quantile(values, 0.90),
        "max": max(values, default=None),
    }


def tolerance_table(
    good_deltas: Sequence[float], flagged_deltas: Mapping[str, Sequence[float]]
) -> list[dict[str, Any]]:
    """Per tolerance: good-file false positives and degradation flags.

    A delta is ``after - before``; "worse" means ``-delta > tolerance``.
    """
    rows = []
    for tolerance in TOLERANCES:
        good = tally([worse_than_before(d, 0.0, tolerance) for d in good_deltas])
        flagged = {
            kind: tally([worse_than_before(d, 0.0, tolerance) for d in deltas])
            for kind, deltas in sorted(flagged_deltas.items())
        }
        rows.append({"tolerance": tolerance, "good": good, "flagged": flagged})
    return rows


def propose_tolerance(table: Sequence[Mapping[str, Any]]) -> float | None:
    """Smallest tolerance whose good-file false-positive rate is at the target."""
    for row in table:
        rate_now = row["good"]["rate"]
        if rate_now is not None and rate_now <= TOLERANCE_FP_TARGET:
            return float(row["tolerance"])
    return None


def p10_spread(scores: Sequence[float], size: int, seed: int = 0) -> dict[str, Any]:
    """Mean and sd of the p10 line over deterministic subsamples of ``size``."""
    if size > len(scores):
        return {"size": size, "n": 0, "mean": None, "sd": None}
    rng = random.Random(f"delta-eval:{seed}:{size}")  # noqa: S311 (seeded)
    lines = [
        reference_line(rng.sample(list(scores), size)) for _ in range(STABILITY_DRAWS)
    ]
    mean = sum(lines) / len(lines)
    sd = math.sqrt(sum((x - mean) ** 2 for x in lines) / len(lines))
    return {"size": size, "n": len(lines), "mean": mean, "sd": sd}


RATE_CELL = re.compile(r"\d+% \(([^)]*)\)")


def missing_n(lines: Sequence[str]) -> list[str]:
    """Lines with a rate cell like ``12% (3/25, n=25)`` lacking ``n=``."""
    return [
        line
        for line in lines
        if any("n=" not in cell for cell in RATE_CELL.findall(line))
    ]
