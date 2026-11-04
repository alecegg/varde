"""Dominance strength derived from the reference (no fixed global value).

The dominance-gating evaluation found no fixed strength that separates tidy
single-function modules from school monoliths. So the strength follows the
reference. ``derive_dominance(reference_records, region)`` returns an integer
micro-unit strength from a fixed grid (0 to 2.0 in steps of 0.25):

* 0 when the reference itself holds a dominant large function (one holding more
  than half the file tokens that exceeds ``Phi`` or ``c0``): it accepts monoliths;
* otherwise the largest grid strength at which no more than 10% of the
  reference's own files fall below ``X``, the reference's own 10th-percentile
  score at strength 0 (the same definition t14 exposes; computed inline here).

Scores only fall as the strength grows, so the feasible strengths form a prefix
of the grid and the choice is unambiguous. Deterministic; no model call.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_measure as bm
import baseline_region as br
import scorer_candidates as sc
from varde_code.quality_score.calibration import Calibration, load_calibration

MICRO = sc.MICRO
GRID = tuple(range(0, 2 * MICRO + 1, MICRO // 4))
LOW_SHARE_PERCENTILE = 10  # X: the reference's own 10th-percentile score
MAX_BELOW_NUMERATOR, MAX_BELOW_DENOMINATOR = 1, 10  # at most 10% of files below X
REFERENCE_ROOT = bm.ROOT / "code/bench/quality-corpus/baseline"

Record = Mapping[str, Any]


def with_region(base: Calibration, language: str, region: br.Region) -> Calibration:
    """``base`` with the region's fitted thresholds substituted (units to micro)."""
    current = base.languages[language]
    fitted = {key: region[key] * MICRO for key in br.FITTED.values() if key in region}
    tuned = replace(current, parameters={**current.parameters, **fitted})
    return replace(base, languages={**base.languages, language: tuned})


def is_dominant_and_large(
    function: Record, file_tokens: int, region: br.Region
) -> bool:
    """More than half of the file tokens, and past the size or cognitive limit."""
    tokens = function.get("tokens") or 0
    cognitive = function.get("cognitive") or 0
    dominant = 2 * tokens > file_tokens
    exceeds = tokens > region["Phi"] or cognitive > region["c0"]
    return dominant and exceeds


def holds_dominant_large(records: Sequence[Record], region: br.Region) -> bool:
    return any(
        is_dominant_and_large(fn, record.get("tokens") or 0, region)
        for record in records
        for fn in record.get("functions", [])
    )


def lower_percentile_score(scores: Sequence[float], percentile: int) -> float:
    """Nearest-rank percentile of scores (lowest value for small samples)."""
    ordered = sorted(scores)
    rank = (percentile * len(ordered) + 99) // 100
    return ordered[max(rank, 1) - 1]


def scores_at(
    records: Sequence[Record], base: Calibration, strength: int
) -> list[float]:
    spec = sc.Spec(f"dominance {strength}", dominance=strength / MICRO)
    return [sc.candidate_score(record, base, spec) for record in records]


def share_below(scores: Sequence[float], line: float) -> tuple[int, int]:
    return sum(1 for s in scores if s < line), len(scores)


def within_budget(scores: Sequence[float], line: float) -> bool:
    below, total = share_below(scores, line)
    return below * MAX_BELOW_DENOMINATOR <= total * MAX_BELOW_NUMERATOR


def derive_dominance(
    reference_records: Sequence[Record],
    region: br.Region,
    base: Calibration | None = None,
    language: str = "python",
) -> int:
    """Dominance strength (integer micro-units) for this reference and region."""
    if not reference_records or holds_dominant_large(reference_records, region):
        return 0
    base = with_region(
        base or load_calibration(bm.DEFAULT_CALIBRATION), language, region
    )
    line = lower_percentile_score(
        scores_at(reference_records, base, 0), LOW_SHARE_PERCENTILE
    )
    chosen = 0
    for strength in GRID:
        if not within_budget(scores_at(reference_records, base, strength), line):
            break
        chosen = strength
    return chosen


def reference_records(reference: str, language: str) -> list[dict[str, Any]]:
    """Facts records of every ``agreed`` example of the language."""
    root = REFERENCE_ROOT / reference
    records: list[dict[str, Any]] = []
    for problem in sorted(p for p in root.iterdir() if p.is_dir()):
        directory = problem / language
        if directory.is_dir():
            records += bm.facts_of_directory(directory, language)
    return records


def check(reference: str, language: str) -> int:
    records = reference_records(reference, language)
    if not records:
        print(f"no {reference} examples for {language}", file=sys.stderr)
        return 2
    base = load_calibration(bm.DEFAULT_CALIBRATION)
    region = {
        k: v
        for k, v in base.languages[language].parameters.items()
        if k in br.FITTED.values()
    }
    region = {k: v // MICRO for k, v in region.items()}
    first = derive_dominance(records, region, base, language)
    if first != derive_dominance(records, region, base, language):
        print("not idempotent", file=sys.stderr)
        return 1
    print(
        f"dominance: {first / MICRO:g} ({first} micro-units) "
        f"language={language} reference={reference} files={len(records)}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--language", default="python", choices=sorted(bm.SUFFIXES))
    parser.add_argument("--reference", default="agreed")
    args = parser.parse_args(argv)
    return check(args.reference, args.language)


if __name__ == "__main__":
    raise SystemExit(main())
