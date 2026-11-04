"""Pure ranking and token-efficiency metrics for the code retrieval benchmark."""

from __future__ import annotations

import math


def ndcg_at_k(ranked: list[str], relevant: set[str], k: int = 10) -> float:
    """Binary relevance NDCG for a ranked list of file paths."""
    if k <= 0 or not relevant:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, item in enumerate(ranked[:k], 1)
        if item in relevant
    )
    ideal = sum(
        1.0 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1)
    )
    return dcg / ideal


def tokens_to_first_hit(
    ranked: list[str], relevant: set[str], token_counts: dict[str, int]
) -> int | None:
    """Tokens read through and including the first relevant file."""
    spent = 0
    for path in ranked:
        spent += token_counts.get(path, 0)
        if path in relevant:
            return spent
    return None


def mean(values: list[float]) -> float:
    """Arithmetic mean, or zero for an empty sample."""
    return sum(values) / len(values) if values else 0.0
