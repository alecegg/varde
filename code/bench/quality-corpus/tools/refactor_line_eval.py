"""Evaluate the relative refactor line and the monolith advisory (no model call).

The line ``X`` is the 10th percentile of the good set's own scores (the
reference). The check requires the good set to keep at least 90% at or above
``X``, reports the share of worse code below ``X`` and the share of school
monoliths the advisory flags, and requires the advisory to stay silent on the
agreed samples. The advisory is computed from facts only, so it cannot change
a score.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import baseline_measure as bm
import score_separation as ss
from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_score import refactor_line as rl

MIN_GOOD_KEPT = 0.9


def advisory_flags(
    sources: Mapping[str, str], limits: Mapping[str, int], language: str = "python"
) -> dict[str, bool]:
    """Whether the monolith advisory fires for each source."""
    return {
        key: rl.monolith_advisory(extract_facts(text, language, "code.py"), limits)
        is not None
        for key, text in sources.items()
    }


def share(flags: Sequence[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def fmt(value: float | None, n: int) -> str:
    return "-" if value is None else f"{100 * value:.0f}% (n={n})"


def line_report(
    items: Sequence[ss.Item],
    scores: Mapping[str, float],
    flags: Mapping[str, bool],
) -> tuple[bool, list[str]]:
    """(passes, report lines) for the refactor line over the labelled items."""
    good = ss.pick(scores, ss.keys_of(items, "good"))
    worse = ss.pick(scores, ss.keys_of(items, "worse"))
    line = rl.reference_line(good)
    kept = 1 - (ss.flagged_share(good, line) or 0.0)
    agreed = [flags[i.key] for i in items if i.key.startswith("agreed:")]
    monoliths = [flags[k] for k in ss.keys_of(items, "contested")]
    ok = kept >= MIN_GOOD_KEPT and not any(agreed)
    return ok, [
        f"refactor line X={line:.1f} (10th percentile of {len(good)} good scores)",
        f"good kept at or above X: {fmt(kept, len(good))}",
        f"worse flagged below X: {fmt(ss.flagged_share(worse, line), len(worse))}",
        f"monolith advisory on monoliths: {fmt(share(monoliths), len(monoliths))}",
        f"monolith advisory on agreed samples: {fmt(share(agreed), len(agreed))}",
        "PASS" if ok else "FAIL",
    ]


def limits_for(calibration_path: Path, language: str = "python") -> dict[str, int]:
    calibration = bm.load_calibration(calibration_path)
    return rl.limits_of(calibration.languages[language].parameters)
