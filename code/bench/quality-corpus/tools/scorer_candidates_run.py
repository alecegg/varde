"""Leave-one-problem-out evaluation of the pre-registered scorer candidates.

    uv run python scorer_candidates_run.py --run-state <dir>... \
        [--cache items.pkl] [--out-json r.json] [--out-txt r.txt]

The candidates are fixed (nothing is fitted); cross-validation only tests that
the cut line (90% of good items kept) set on the other problems transfers to the
held-out one. Proxy modules are good items in every fold. No model call.
"""

from __future__ import annotations

import argparse
import json
import pickle
import statistics
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_run as ir
import baseline_measure as bm
import baseline_rank_run as rr
import discrimination_run as drun
import score_separation as ss
import score_separation_run as ssr
import score_variants as sv
import scorer_candidates as sc


def load_items(args: argparse.Namespace) -> tuple[list, dict, list[str]]:
    """(items, measured records by key, problems), optionally from a pickle."""
    if args.cache and args.cache.exists():
        items, _, records, problems = pickle.loads(args.cache.read_bytes())  # noqa: S301 (own cache)
        return items, records, problems
    repos = [rr.REFERENCE_ROOT / name for name in rr.DEFAULT_REFERENCE]
    files = ssr.blob_files(ir.DEFAULT_CACHE, 40, [r for r in repos if r.is_dir()])
    agreed = {
        p.parent.parent.name: p.read_text()
        for p in sorted(ir.AGREED_ROOT.glob("*/python/solution.py"))
    }
    degraded = drun.degraded_sources(agreed)
    items, sources = ssr.build_items(
        agreed,
        ssr.proxy_sources(files),
        degraded,
        ssr.monolith_sources(args.run_state),
    )
    records = {k: sv.measured_record(s) for k, s in sources.items()}
    if args.cache:
        args.cache.write_bytes(pickle.dumps((items, sources, records, sorted(agreed))))
    return items, records, sorted(agreed)


def fold_result(
    scores: ss.Scores, items: Sequence[ss.Item], problems: Sequence[str], held: str
) -> dict[str, Any]:
    parts = ss.split_for_problem(items, problems, held)
    cut = ss.cut_line(ss.pick(scores, parts["train"]["good"]))
    test = parts["test"]
    good = ss.pick(scores, test["good"])
    worse_keys, mono_keys = test["worse"], test["contested"]
    kinds = ss.kinds_of(items)
    return {
        "cut": cut,
        "good": good,
        "worse": ss.pick(scores, worse_keys),
        "mono": ss.pick(scores, mono_keys),
        "kind_counts": ss.kind_counts(scores, worse_keys, kinds, cut),
        "mono_flagged": sum(s < cut - ss.EPS for s in ss.pick(scores, mono_keys)),
    }


def pooled_auc(folds: Sequence[Mapping[str, Any]], field: str) -> float | None:
    """Pair-weighted AUC of good over ``field`` pooled across folds."""
    num = den = 0.0
    for f in folds:
        pairs = len(f["good"]) * len(f[field])
        auc = ss.good_above_auc(f["good"], f[field])
        if pairs and auc is not None:
            num, den = num + auc * pairs, den + pairs
    return num / den if den else None


def cv_summary(
    scores: ss.Scores, items: Sequence[ss.Item], problems: Sequence[str]
) -> dict[str, Any]:
    return cv_summary_of([fold_result(scores, items, problems, p) for p in problems])


def cv_summary_of(folds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_kind: dict[str, list[int]] = {}
    for fold in folds:
        for kind, (hit, total) in fold["kind_counts"].items():
            entry = by_kind.setdefault(kind, [0, 0])
            entry[0], entry[1] = entry[0] + hit, entry[1] + total
    worse_n = sum(t for _, t in by_kind.values())
    mono_n = sum(len(f["mono"]) for f in folds)
    return {
        "auc_worse": pooled_auc(folds, "worse"),
        "auc_mono": pooled_auc(folds, "mono"),
        "sens": sum(h for h, _ in by_kind.values()) / max(worse_n, 1),
        "mono_sens": sum(f["mono_flagged"] for f in folds) / max(mono_n, 1),
        "by_kind": {k: h / t for k, (h, t) in sorted(by_kind.items())},
        "mean_cut": statistics.fmean(f["cut"] for f in folds),
    }


def paired_drops(scores: ss.Scores, items: Sequence[ss.Item]) -> dict[str, float]:
    """Mean agreed-minus-variant drop per kind and agreed-minus-monolith."""
    agreed = {
        i.key.removeprefix("agreed:"): scores[i.key]
        for i in items
        if i.key.startswith("agreed:")
    }
    variants = {
        kind: {i.key.split(":", 1)[1]: scores[i.key] for i in items if i.kind == kind}
        for kind in sorted({i.kind for i in items if i.kind})
    }
    drops = {
        k: statistics.fmean(p["deltas"].values())
        for k, p in ss.paired_deltas(agreed, variants).items()
    }
    mono = [
        agreed[i.problem] - scores[i.key]
        for i in items
        if i.role == "contested" and i.problem in agreed
    ]
    drops["monolith"] = statistics.fmean(mono)
    return drops


def in_sample(scores: ss.Scores, items: Sequence[ss.Item]) -> dict[str, float | None]:
    good = ss.pick(scores, ss.keys_of(items, "good"))
    return {
        "auc_worse": ss.good_above_auc(
            good, ss.pick(scores, ss.keys_of(items, "worse"))
        ),
        "auc_mono": ss.good_above_auc(
            good, ss.pick(scores, ss.keys_of(items, "contested"))
        ),
    }


def objective(scores: ss.Scores, part: Mapping[str, list[str]]) -> float:
    """Mean of AUC good>worse and good>monolith on a training part."""
    good = ss.pick(scores, part["good"])
    aucs = [
        ss.good_above_auc(good, ss.pick(scores, part[role])) or 0.0
        for role in ("worse", "contested")
    ]
    return statistics.fmean(aucs)


def nested_selection(
    tables: Mapping[str, ss.Scores], items: Sequence[ss.Item], problems: Sequence[str]
) -> dict[str, Any]:
    """Choose a candidate on the training problems, test on the held-out one."""
    folds, chosen = [], []
    for held in problems:
        parts = ss.split_for_problem(items, problems, held)
        best = max(tables, key=lambda n: objective(tables[n], parts["train"]))
        chosen.append(best)
        folds.append(fold_result(tables[best], items, problems, held))
    summary = cv_summary_of(folds)
    return {**summary, "chosen": chosen}


def pct(v: float | None) -> str:
    return "-" if v is None else f"{100 * v:.0f}%"


def num(v: float | None, d: int = 2) -> str:
    return "-" if v is None else f"{v:.{d}f}"


def report(rows: Sequence[Mapping[str, Any]]) -> str:
    kinds = list(rows[0]["cv"]["by_kind"])
    lines = [
        "Scorer candidates, leave-one-problem-out (cut from training good, 90% kept)",
        (
            "candidate | CV AUC good>worse | CV AUC good>monolith | sens@90 | "
            "monolith flagged | cut | in-sample AUC w/m"
        ),
    ]
    for r in rows:
        cv = r["cv"]
        lines.append(
            f"{r['name']} | {num(cv['auc_worse'])} | {num(cv['auc_mono'])} | "
            f"{pct(cv['sens'])} | {pct(cv['mono_sens'])} | {num(cv['mean_cut'], 1)} | "
            f"{num(r['in_sample']['auc_worse'])}/{num(r['in_sample']['auc_mono'])}"
        )
    lines += ["", "sensitivity at 90% specificity by degradation type (CV)"]
    lines.append("candidate | " + " | ".join(kinds))
    for r in rows:
        lines.append(
            f"{r['name']} | " + " | ".join(pct(r["cv"]["by_kind"][k]) for k in kinds)
        )
    drop_kinds = list(rows[0]["drops"])
    lines += ["", "paired within-problem drop (agreed minus variant, mean points)"]
    lines.append("candidate | " + " | ".join(drop_kinds))
    for r in rows:
        lines.append(
            f"{r['name']} | " + " | ".join(num(r["drops"][k], 1) for k in drop_kinds)
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-state", type=Path, nargs="+", required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-txt", type=Path)
    args = parser.parse_args(argv)
    items, records, problems = load_items(args)
    base = bm.load_calibration(bm.DEFAULT_CALIBRATION)
    rows = []
    for spec in (*sc.CANDIDATES, *sc.ROUND2, *sc.ROUND3):
        scores = {k: sc.candidate_score(r, base, spec) for k, r in records.items()}
        rows.append(
            {
                "name": spec.name,
                "cv": cv_summary(scores, items, problems),
                "in_sample": in_sample(scores, items),
                "drops": paired_drops(scores, items),
                "scores": scores,
            }
        )
    tables = {r["name"]: r["scores"] for r in rows}
    nested = nested_selection(tables, items, problems)
    text = (
        report(rows)
        + "\n\nnested selection (train objective = mean of both AUCs): "
        + json.dumps(nested, sort_keys=True)
    )
    if args.out_json:
        args.out_json.write_text(json.dumps(rows, indent=1, sort_keys=True))
    if args.out_txt:
        args.out_txt.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
