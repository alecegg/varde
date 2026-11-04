"""File-level advisories beside the monolith one; they never change the score.

Both read per-function facts and fire on a whole file. The cut points are the
10th/90th percentile of good files, with the false-flag rates measured in
``file-features.md`` (plan 2026-10-31-vqs-example-baseline, t18):

- ``delegation_share`` above 1/7 (``0.142857``): wrappers 80-85%, deep chains
  90%; 9% of good files flagged.
- ``tokens_p50`` below 32 tokens: deep chains 64-78%, wrappers 38-56%; 9% of
  good files flagged.

Both cut points and rates were measured on Python files only, so the advisories
fire for Python paths (``.py``, ``.pyi``) and stay silent for other languages
until their cut points are measured.

The cut for exact rows is the good-file 90th percentile of the exact share
(``EXACT_DELEGATION_SHARE_CUT``, 1/3): flags 8% of good files (n=132), wrappers
77% and deep chains 100% (n=119 each); the 1/7 cut belongs to the proxy.

A row with ``delegates`` set (``raw_measure``: the whole body is one call, a
docstring ignored) is exact. A row without it falls back to the proxy of
``code/bench/quality-corpus/tools/file_features.py`` (one callee, no branching, at
most 30 tokens), ported here because ``code`` cannot import ``bench``; a test
keeps the two equal. Pure functions; no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any

DELEGATE_MAX_TOKENS = 30
DELEGATION_SHARE_CUT = Fraction(1, 7)  # t18 file-features.md: good p90 = 0.142857
# Good p90 of the exact share (measure_quantiles.py --compare-proxy, dev split).
EXACT_DELEGATION_SHARE_CUT = Fraction(1, 3)
TOKENS_P50_LOW_CUT = 32  # t18 file-features.md: good p10 of the median function size


def is_python_path(path: str) -> bool:
    return path.endswith((".py", ".pyi"))


def is_delegation(row: Mapping[str, Any]) -> bool:
    """Exact when the row has ``delegates``; else the proxy (one small callee)."""
    exact = row.get("delegates")
    if exact is not None:
        return bool(exact)
    return (
        row.get("fan_out") == 1
        and row.get("cognitive") == 0
        and (row.get("tokens") or 0) <= DELEGATE_MAX_TOKENS
    )


def delegation_share(rows: Sequence[Mapping[str, Any]]) -> float | None:
    if not rows:
        return None
    return sum(is_delegation(row) for row in rows) / len(rows)


def exact_delegation_share(rows: Sequence[Mapping[str, Any]]) -> float | None:
    """Share of rows whose whole body is one call; ``None`` without exact rows."""
    known = [row["delegates"] for row in rows if row.get("delegates") is not None]
    if not known:
        return None
    return sum(known) / len(known)


def tokens_p50(rows: Sequence[Mapping[str, Any]]) -> int | None:
    """Nearest-rank median of the functions' token counts."""
    tokens = sorted(row["tokens"] for row in rows if row.get("tokens") is not None)
    if not tokens:
        return None
    rank = (50 * len(tokens) + 99) // 100
    return tokens[max(rank, 1) - 1]


def delegation_advisory(record: Mapping[str, Any]) -> dict[str, Any] | None:
    functions = record.get("functions") or []
    if not functions or not is_python_path(str(record["path"])):
        return None
    count = sum(is_delegation(fn) for fn in functions)
    exact = all(fn.get("delegates") is not None for fn in functions)
    cut = EXACT_DELEGATION_SHARE_CUT if exact else DELEGATION_SHARE_CUT
    if Fraction(count, len(functions)) <= cut:
        return None
    percent = count * 100 // len(functions)
    path = str(record["path"])
    return {
        "file": path,
        "share_percent": percent,
        "action": (
            f"{percent}% of the functions in `{path}` only forward one call: "
            "inline the wrappers into their callers or give them real work"
        ),
    }


def fragmentation_advisory(record: Mapping[str, Any]) -> dict[str, Any] | None:
    median = tokens_p50(record.get("functions") or [])
    if median is None or median >= TOKENS_P50_LOW_CUT:
        return None
    if not is_python_path(str(record["path"])):
        return None
    path = str(record["path"])
    return {
        "file": path,
        "median_tokens": median,
        "action": (
            f"the median function in `{path}` is only {median} tokens: merge "
            "closely related tiny functions into fewer, fuller ones"
        ),
    }
