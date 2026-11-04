"""Acceptable-quality region: calibrate per-language thresholds from k examples.

Pure, deterministic functions (no model call). The region is the existing
per-language threshold vector (cal-1 keys). Each fitted raw measure moves from
its default toward the examples' 90th percentile by ``k / (k + 2)`` and is
clamped to the corpus [q50, q99]. All arithmetic is integer; example order is
irrelevant. ``--probe-schema`` checks that a cal-1 draft loads and scores
through the unchanged calibration loader.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
CODE_SRC = ROOT / "code/src"
if str(CODE_SRC) not in sys.path:
    sys.path.insert(0, str(CODE_SRC))

DEFAULT_CALIBRATION = CODE_SRC / "varde_code/quality_score/calibration/placeholder.toml"
# raw measure (raw_measure.py row key) -> cal-1 language threshold key
FITTED = {
    "cognitive": "c0",
    "depth": "dp0",
    "fan_out": "k0",
    "tree_size": "t0",
    "params": "p0",
    "tokens": "Phi",
}
REPORT_ONLY = ("max_nesting", "name_issues")  # measured, no calibration key
ANCHOR_PERCENTILE = 90
LOW_PERCENTILE, HIGH_PERCENTILE = 50, 99
WEIGHT_OFFSET = 2  # w = k / (k + WEIGHT_OFFSET)
# Keys cal-1 adds to the installed schema; the probe shows the loader accepts them.
CAL1_LANGUAGE_KEYS = ("p0",)
CAL1_GLOBAL_KEYS = ("dominance",)
PROBE_DOMINANCE = "0.5"
PROBE_X = "55"

Region = Mapping[str, int]


def nearest_rank(values: Sequence[int], percentile: int) -> int | None:
    """Nearest-rank percentile (integer arithmetic); None when empty."""
    if not values:
        return None
    ordered = sorted(values)
    rank = (percentile * len(ordered) + 99) // 100
    return ordered[max(rank, 1) - 1]


def example_values(rows: Sequence[Mapping[str, Any]], measure: str) -> list[int]:
    return [int(r[measure]) for r in rows if r.get(measure) is not None]


def corpus_bounds(values: Sequence[int]) -> tuple[int, int] | None:
    """Corpus [q50, q99] of one measure, or None without corpus values."""
    low = nearest_rank(values, LOW_PERCENTILE)
    high = nearest_rank(values, HIGH_PERCENTILE)
    return None if low is None or high is None else (low, high)


def shifted(default: int, anchor: int, k: int) -> int:
    """default + k/(k+2) * (anchor - default), rounded half up, integers only."""
    denominator = k + WEIGHT_OFFSET
    return default + (2 * k * (anchor - default) + denominator) // (2 * denominator)


def fit_threshold(
    default: int,
    values: Sequence[int],
    k: int,
    bounds: tuple[int, int] | None,
) -> int:
    anchor = nearest_rank(values, ANCHOR_PERCENTILE)
    if k <= 0 or anchor is None:
        return default
    threshold = shifted(default, anchor, k)
    if bounds is None:
        return threshold
    return min(max(threshold, bounds[0]), bounds[1])


def calibrate(
    default_region: Region,
    examples: Sequence[Sequence[Mapping[str, Any]]],
    corpus: Mapping[str, Sequence[int]],
) -> dict[str, int]:
    """Threshold set (same keys as ``default_region``) from k example samples.

    ``examples`` is one sequence of raw per-function rows per sample;
    ``corpus`` maps a raw measure to the language's verified-corpus values.
    """
    rows = [row for sample in examples for row in sample]
    region = dict(sorted(default_region.items()))
    for measure, key in FITTED.items():
        if key not in region:
            continue
        region[key] = fit_threshold(
            region[key],
            example_values(rows, measure),
            len(examples),
            corpus_bounds(list(corpus.get(measure, ()))),
        )
    return region


def inside_region(function: Mapping[str, Any], region: Region) -> bool:
    """Every fitted raw measure is at or below its threshold."""
    return all(
        function.get(measure) is None or function[measure] <= region[key]
        for measure, key in FITTED.items()
        if key in region
    )


# ---- schema probe -----------------------------------------------------------


def draft_text(placeholder: str) -> str:
    """The placeholder with ``p0``, ``dominance`` and a different ``X`` added."""
    lines = []
    section = ""
    for source_line in placeholder.splitlines():
        line = source_line
        if line.startswith("["):
            section = line
        if line.startswith("X = ") and section.startswith("[language."):
            line = f'X = "{PROBE_X}"'
        lines.append(line)
        if line.startswith("[global]"):
            lines.append(f'dominance = "{PROBE_DOMINANCE}"')
        if line.startswith("t0 = "):
            lines.append("p0 = 2")
    return "\n".join(lines) + "\n"


PROBE_SOURCE = (
    "def f(a, b, c, d, e):\n    return a\n\n\ndef g(x):\n    return f(x, 1, 2, 3, 4)\n"
)


def probe_schema(calibration_path: Path) -> tuple[bool, str]:
    """Load and score a cal-1 draft through the unchanged loader."""
    import baseline_measure as bm
    from varde_code.quality_score.calibration import load_calibration

    text = draft_text(calibration_path.read_text())
    data = tomllib.loads(text)
    with tempfile.TemporaryDirectory() as tmp:
        draft = Path(tmp) / "cal-1-draft.toml"
        draft.write_text(text)
        loaded = load_calibration(draft)
        base = bm.score_source(
            PROBE_SOURCE, "python", load_calibration(calibration_path)
        )
        scored = bm.score_source(PROBE_SOURCE, "python", loaded)
    python = loaded.languages["python"].parameters
    ok = (
        "p0" in python
        and "dominance" in loaded.global_strengths
        and python["X"] == int(data["language"]["python"]["X"]) * 1_000_000
        and scored.get("score") is not None
        and scored.get("score") != base.get("score")
    )
    return ok, f"base={base.get('score')} draft={scored.get('score')}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-schema", action="store_true", required=True)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    args = parser.parse_args(argv)
    try:
        ok, detail = probe_schema(args.calibration)
    except (ValueError, TypeError, KeyError) as exc:
        print(f"schema-change: yes ({type(exc).__name__}: {exc})")
        return 3
    print(f"schema-change: {'no' if ok else 'yes'} ({detail})")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
