"""Bench-only calibration variants and record builders for the top-line score
(no scorer change, no model call).

Two record pipelines feed ``score_scope``:

* ``facts`` is what ``baseline_measure.score_source`` scores: facts of one file,
  no graph measures, so depth, fan_out and tree_size are absent and their pools
  are empty;
* ``measured`` merges the quality pass measures (call resolution and graph
  measures) into the facts like the stored scan records, so structure costs
  exist and ``structure_confidence`` can gate them.

A variant changes the Python thresholds, scales the component strengths and
picks how structure costs are gated; the shipped calibration file is not edited.
"""

from __future__ import annotations

import itertools
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_measure as bm
from varde_code.quality_pass import resolve_hook
from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_pass.pass_.measures import compute_measures
from varde_code.quality_score.calibration import Calibration

MICRO = 1_000_000
PATH = "module.py"
# strength set -> strengths doubled (cognitive and long side apply their strength
# twice in the shipped formula: once in the cost, once as the component weight)
STRENGTH_SETS = {
    "x1": (),
    "cog2": ("w", "wL"),
    "struct2": ("structure",),
    "names2": ("names",),
    "all2": ("w", "wL", "structure", "names"),
}
GATES = ("gated", "ungated", "ungated-metrics")
# discrimination-report-2 (directional) thresholds of the matched signals
BASELINE_COGNITIVE_STRUCTURE = (("c0", 6), ("dp0", 3), ("k0", 3), ("t0", 5))
BASELINE_NO_SHORT = (*BASELINE_COGNITIVE_STRUCTURE, ("p0", 2), ("Phi", 112))
BASELINE_ALL = (*BASELINE_NO_SHORT, ("Plo", 59))
THRESHOLD_SETS = {
    "placeholder": (),
    "base-cog-struct": BASELINE_COGNITIVE_STRUCTURE,
    "base-no-short": BASELINE_NO_SHORT,
    "base-all": BASELINE_ALL,
}
# single-threshold ablations: reported in-sample, never used for selection
ABLATION_SETS = {
    "only-c0": (("c0", 6),),
    "only-struct": (("dp0", 3), ("k0", 3), ("t0", 5)),
    "only-p0": (("p0", 2),),
    "only-Phi": (("Phi", 112),),
    "only-Plo": (("Plo", 59),),
}


@dataclass(frozen=True)
class Variant:
    thresholds: str
    strengths: str
    gate: str

    @property
    def name(self) -> str:
        return f"{self.thresholds}|{self.strengths}|{self.gate}"


def ablations() -> list[Variant]:
    return [Variant(t, "x1", g) for t in ABLATION_SETS for g in ("gated", "ungated")]


def candidates() -> list[Variant]:
    """Default first, then a small fixed grid (no continuous search)."""
    grid = itertools.product(THRESHOLD_SETS, STRENGTH_SETS, GATES)
    return [Variant(t, s, g) for t, s, g in grid]


def calibrated(base: Calibration, variant: Variant) -> Calibration:
    """Python thresholds and strengths of ``variant`` applied to a copy of ``base``."""
    language = base.languages["python"]
    named = {**THRESHOLD_SETS, **ABLATION_SETS}
    changed = {k: v * MICRO for k, v in named[variant.thresholds]}
    strengths = dict(base.global_strengths)
    for name in STRENGTH_SETS[variant.strengths]:
        strengths[name] = strengths.get(name, MICRO) * 2
    tuned = replace(language, parameters={**language.parameters, **changed})
    return replace(
        base, languages={**base.languages, "python": tuned}, global_strengths=strengths
    )


def facts_record(source: str) -> dict[str, Any]:
    return extract_facts(source.encode(), "python", PATH)


def merge_measures(facts: Mapping[str, Any], measured: Mapping[str, Any]) -> dict:
    """Facts plus the L3 measures of one file, like a stored scan record."""
    by_id = measured["functions"]
    functions = [{**f, **by_id.get(str(f["id"]), {})} for f in facts["functions"]]
    return {
        **facts,
        "functions": functions,
        "structure_confidence": measured["structure_confidence"],
        "import_fan_out": measured["import_fan_out"],
        "call_coverage": measured["call_coverage"],
    }


def measured_record(source: str) -> dict[str, Any]:
    facts = {PATH: facts_record(source)}
    context = resolve_hook.prepare([PATH], facts)
    edges = {PATH: resolve_hook.edges_for_file(context, PATH)}
    measured = compute_measures(facts, edges, {PATH: "."})[PATH]
    return merge_measures(facts[PATH], measured)


def gated_record(record: Mapping[str, Any], gate: str) -> dict[str, Any]:
    """``ungated`` counts structure costs at low confidence; ``-metrics`` drops
    fragmentation (which needs reliable call counts) but keeps depth, fan_out
    and tree_size."""
    if gate == "gated":
        return dict(record)
    ungated = {**record, "structure_confidence": "normal"}
    if gate == "ungated":
        return ungated
    functions = [{**f, "fragment_scope": None} for f in record["functions"]]
    return {**ungated, "functions": functions}


def top_line(record: Mapping[str, Any], calibration: Calibration) -> dict[str, Any]:
    """The same scope -> explain -> breakdown -> user_view path as score_source."""
    scored = bm.score_scope([dict(record)], calibration)
    payload = bm.explain(scored)
    payload["calibration"] = calibration.output_label
    return bm.user_view(payload, bm.breakdown(scored, calibration), None)


def score_of(
    record: Mapping[str, Any], calibration: Calibration, gate: str = "gated"
) -> float | None:
    return top_line(gated_record(record, gate), calibration)["score"]
