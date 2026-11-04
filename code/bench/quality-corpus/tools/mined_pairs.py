"""Pure helpers for scoring mined refactor pairs (parent before, child after).

No I/O and no model call: statistics, intent tags, size buckets, changed-function
selection and guidance hit rates over per-file score rows.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Mapping, Sequence

INTENT_TAGS = {
    "simplify": r"simplif",
    "extract": r"extract",
    "flatten": r"flatten",
    "early return": r"early[ -]return",
    "rename": r"renam",
    "split": r"\bsplit",
    "reduce complexity": r"reduc\w* complexity",
    "cleanup": r"clean\s?up",
    "readability": r"readab",
}
SIZE_BUCKETS = ((0, 1000, "<1k tokens"), (1000, 3000, "1k-3k"), (3000, 10**9, ">=3k"))


def intent_tags(message: str) -> list[str]:
    lowered = message.lower()
    return [t for t, pattern in INTENT_TAGS.items() if re.search(pattern, lowered)]


def size_bucket(tokens: int) -> str:
    return next(label for lo, hi, label in SIZE_BUCKETS if lo <= tokens < hi)


def function_name(function_id: str) -> str:
    """Plain name of an id like ``module.py::A.f#1``."""
    tail = function_id.split("::")[-1].split("#")[0]
    return tail.split(".")[-1]


def sign_test_p(wins: int, losses: int) -> float:
    """Two-sided exact binomial p-value (ties excluded)."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired_stats(deltas: Sequence[float], eps: float = 1e-9) -> dict[str, float]:
    """Agreement of after-minus-before deltas with 'after is better'."""
    n = len(deltas)
    if n == 0:
        return {"n": 0}
    up = sum(d > eps for d in deltas)
    down = sum(d < -eps for d in deltas)
    return {
        "n": n,
        "up": up / n,
        "tie": (n - up - down) / n,
        "down": down / n,
        "mean": statistics.fmean(deltas),
        "median": statistics.median(deltas),
        "sign_p": sign_test_p(up, down),
    }


def changed_density(
    debts: Mapping[str, int], tokens: Mapping[str, int], names: set[str]
) -> tuple[int, int] | None:
    """(debt, tokens) summed over functions whose plain name is in ``names``."""
    ids = [i for i in debts if function_name(i) in names]
    total = sum(tokens.get(i, 0) for i in ids)
    if not ids or total <= 0:
        return None
    return sum(debts[i] for i in ids), total


def worst_ids(debts: Mapping[str, int], count: int = 3) -> list[str]:
    ranked = sorted(debts, key=lambda i: (-debts[i], i))
    return [i for i in ranked[:count] if debts[i] > 0]


def hit(top_ids: Sequence[str], names: set[str]) -> bool | None:
    """None when there is nothing to point at."""
    if not top_ids:
        return None
    return any(function_name(i) in names for i in top_ids)


def chance_hit(function_total: int, changed_total: int, count: int = 3) -> float:
    """Probability that ``count`` random functions include a changed one."""
    if function_total <= 0:
        return 0.0
    picks = min(count, function_total)
    others = function_total - changed_total
    if others < picks:
        return 1.0
    return 1 - math.comb(others, picks) / math.comb(function_total, picks)


def rate(flags: Sequence[bool | None]) -> float | None:
    known = [f for f in flags if f is not None]
    return sum(known) / len(known) if known else None


def share_below(values: Sequence[float], cut: float) -> float | None:
    return sum(v < cut for v in values) / len(values) if values else None


def cut_accuracy(
    before: Sequence[float], after: Sequence[float], cut: float
) -> float | None:
    """Accuracy of 'below cut = needs refactor' with before=needs, after=ok."""
    total = len(before) + len(after)
    if not total:
        return None
    correct = sum(v < cut for v in before) + sum(v >= cut for v in after)
    return correct / total
