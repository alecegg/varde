"""Does the fix guidance of the user view point at what was degraded?

For each agreed solution and each behaviour-preserving degradation of
``quality_degrade`` (no model call, deterministic) this reports

* attribution: is the category with the largest points lost against the source
  the one matching the injected degradation;
* hit: does the top-3 function list of the matching category contain a function
  the degradation touched (new id, or changed size, complexity, parameters,
  name issues or call-graph measures);
* recovery: score gain of reverting the degradation (the source score), and the
  recoverable points the breakdown itself claims for the attributed category.

    uv run python guidance_run.py [--out-json r.json] [--out-txt r.txt] [--example]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_measure as bm
import quality_degrade as qd
import score_variants as sv
from varde_code.quality_score.breakdown import breakdown
from varde_code.quality_score.calibration import Calibration, load_calibration
from varde_code.quality_score.user_text import render_text
from varde_code.quality_score.user_view import user_view

AGREED = Path(__file__).resolve().parent.parent / "baseline/agreed"
MICRO = 1_000_000
CORE = ("cognitive", "long_side", "small_side", "params", "names")
STRUCTURE = ("depth", "fan_out", "tree_size", "fragmentation")
EXPECTED = {
    "rename_vague": ("names",),
    "add_params": ("params",),
    "inline_helpers": ("cognitive", "long_side"),
    "guard_nesting": ("cognitive", "long_side"),
    "compound": ("cognitive", "long_side"),
    "wrappers": ("small_side",),
    "deep_chain": STRUCTURE,
}
FACT_KEYS = (
    "tokens",
    "cognitive",
    "params",
    "name_issues",
    "depth",
    "fan_out",
    "tree_size",
)


# ---- pure helpers -----------------------------------------------------------


def points_by_category(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {row["name"]: row["points_lost"] for row in rows}


def loss_increase(
    source: Mapping[str, int], degraded: Mapping[str, int]
) -> dict[str, int]:
    names = sorted(set(source) | set(degraded))
    return {n: degraded.get(n, 0) - source.get(n, 0) for n in names}


def largest(increase: Mapping[str, int], allowed: Sequence[str]) -> str | None:
    """Category with the largest increase (ties: name order); None if none rose."""
    ranked = sorted(
        ((v, n) for n, v in increase.items() if n in allowed and v > 0),
        key=lambda item: (-item[0], item[1]),
    )
    return ranked[0][1] if ranked else None


def top_categories(
    increase: Mapping[str, int], allowed: Sequence[str], count: int = 3
) -> list[str]:
    ranked = sorted(
        ((v, n) for n, v in increase.items() if n in allowed and v > 0),
        key=lambda item: (-item[0], item[1]),
    )
    return [n for _, n in ranked[:count]]


def touched_ids(
    source: Sequence[Mapping[str, Any]], degraded: Sequence[Mapping[str, Any]]
) -> set[str]:
    """Degraded function ids that are new or whose measured facts changed."""
    before = {f["id"]: _facts_of(f) for f in source}
    return {f["id"] for f in degraded if before.get(f["id"]) != _facts_of(f)}


def _facts_of(function: Mapping[str, Any]) -> tuple:
    return tuple(json.dumps(function.get(key), sort_keys=True) for key in FACT_KEYS)


def top_hit(top_ids: Sequence[str], touched: set[str]) -> bool | None:
    """None when the category lists no functions (file-level targets)."""
    return any(i in touched for i in top_ids) if top_ids else None


def rate(flags: Sequence[bool | None]) -> float | None:
    known = [f for f in flags if f is not None]
    return round(sum(known) / len(known), 3) if known else None


# ---- evaluation -------------------------------------------------------------


def score_record(
    source: str, calibration: Calibration
) -> tuple[dict, dict, list[dict]]:
    """(record, user view with guidance, breakdown rows) of one module."""
    record = sv.measured_record(source)
    scored = bm.score_scope([record], calibration)
    payload = bm.explain(scored)
    payload["calibration"] = calibration.output_label
    rows = breakdown(scored, calibration, [record])
    return record, user_view(payload, rows), rows


def evaluate(source: str, kind: str, calibration: Calibration) -> dict[str, Any] | None:
    """Attribution, hit and recovery for one degraded variant; None for a no-op."""
    base = qd.identity(source)
    degraded = qd.DEGRADATIONS[kind](source)
    if degraded == base:
        return None
    src_rec, src_view, src_rows = score_record(base, calibration)
    deg_rec, deg_view, deg_rows = score_record(degraded, calibration)
    increase = loss_increase(points_by_category(src_rows), points_by_category(deg_rows))
    expected = EXPECTED[kind]
    attributed = largest(increase, [*CORE, *STRUCTURE])
    matching = largest(increase, expected)
    top = _top_ids(deg_rows, matching)
    touched = touched_ids(src_rec["functions"], deg_rec["functions"])
    return {
        "kind": kind,
        "source_score": src_view["score"],
        "degraded_score": deg_view["score"],
        "attributed_all": attributed,
        "attributed_core": largest(increase, CORE),
        "matching": matching,
        "attribution_ok": attributed in expected,
        "attribution_core_ok": largest(increase, CORE) in expected,
        "attribution_top3_ok": any(
            n in expected for n in top_categories(increase, [*CORE, *STRUCTURE])
        ),
        "hit": top_hit(top, touched),
        "recovery_revert": round(src_view["score"] - deg_view["score"], 1),
        "recoverable_claimed": _recoverable(deg_rows, attributed),
        "view": deg_view,
    }


def _top_ids(rows: Sequence[Mapping[str, Any]], category: str | None) -> list[str]:
    row = next((r for r in rows if r["name"] == category), None)
    if row is None:
        return []
    return [t["id"] for t in row["fix_targets"] if t["line"] is not None]


def _recoverable(rows: Sequence[Mapping[str, Any]], category: str | None) -> float:
    row = next((r for r in rows if r["name"] == category), None)
    return round(row["points_recoverable"] / MICRO**2, 1) if row else 0.0


def summarize(results: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_kind: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for result in results:
        by_kind[result["kind"]].append(result)
    return {kind: _kind_summary(items) for kind, items in sorted(by_kind.items())}


def _kind_summary(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(items)
    return {
        "n": n,
        "attribution_all": rate([r["attribution_ok"] for r in items]),
        "attribution_core": rate([r["attribution_core_ok"] for r in items]),
        "attribution_top3": rate([r["attribution_top3_ok"] for r in items]),
        "hit": rate([r["hit"] for r in items]),
        "hit_n": sum(r["hit"] is not None for r in items),
        "mean_recovery_revert": round(sum(r["recovery_revert"] for r in items) / n, 1),
        "mean_recoverable_claimed": round(
            sum(r["recoverable_claimed"] for r in items) / n, 1
        ),
    }


def run(
    sources: Mapping[str, str], calibration: Calibration
) -> tuple[list[dict], dict]:
    results = []
    for problem, source in sorted(sources.items()):
        for kind in qd.DEGRADATIONS:
            result = evaluate(source, kind, calibration)
            if result:
                results.append({"problem": problem, **result})
    return results, summarize(results)


def format_report(summary: Mapping[str, Mapping[str, Any]]) -> str:
    columns = ("type", "n", "attr_all", "attr_core", "attr_top3", "hit(n)")
    columns += ("revert_gain", "claimed_recoverable")
    lines = ["  ".join(columns)]
    for kind, s in summary.items():
        cells = (
            kind,
            s["n"],
            s["attribution_all"],
            s["attribution_core"],
            s["attribution_top3"],
            f"{s['hit']}({s['hit_n']})",
            s["mean_recovery_revert"],
            s["mean_recoverable_claimed"],
        )
        lines.append("  ".join(str(c) for c in cells))
    return "\n".join(lines) + "\n"


def agreed_sources(directory: Path = AGREED) -> dict[str, str]:
    return {
        p.parent.parent.name: p.read_text()
        for p in sorted(directory.glob("*/python/solution.py"))
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-txt", type=Path)
    parser.add_argument("--example", help="print the text view of this kind")
    args = parser.parse_args(argv)
    calibration = load_calibration(bm.DEFAULT_CALIBRATION)
    results, summary = run(agreed_sources(), calibration)
    report = format_report(summary)
    print(report, end="")
    if args.example:
        example = next(r for r in results if r["kind"] == args.example)
        print(render_text(example["view"]), end="")
        print(json.dumps(example["view"], sort_keys=True))
    if args.out_json:
        slim = [{k: v for k, v in r.items() if k != "view"} for r in results]
        args.out_json.write_text(
            json.dumps({"summary": summary, "rows": slim}, indent=1)
        )
    if args.out_txt:
        args.out_txt.write_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
