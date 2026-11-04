# ruff: noqa: E501  (report text templates)
"""Evaluate dominance-gating candidates (no model call).

    uv run python dominance_gating_run.py --cache items.pkl --extra extra.pkl \
        [--out-json r.json] [--out-txt r.txt]

``items.pkl`` is the scorer_candidates cache; ``extra.pkl`` (built on first use)
holds measured records of the 40 tidy few-function modules and the 14 mechanical
monoliths with their original modules. The tidy set is split deterministically
(alternating in content-hash order) into two halves of 20: one half joins the good
items for the cut line, the other is held out for false positives; both
directions are pooled. Agreed/degradation/school parts use leave-one-problem-out.
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
import dominance_gating as dg
import pd2_validation as pv
import pd2_validation_run as pr
import score_separation as ss
import score_variants as sv
import scorer_candidates_run as scr

PLACEHOLDER = dg.Candidate("placeholder", dg.gate_none, 0.0)


def build_extra(items_cache: Path, bench_cache: Path) -> dict[str, Any]:
    _, sources, _, _ = pickle.loads(items_cache.read_bytes())  # noqa: S301
    used = {pv.content_key(s.encode()) for s in sources.values()}
    pool = pr.usable({**pr.corpus_pool(bench_cache), **pr.reference_pool()}, used)
    tidy = {
        k: v
        for k, v in pool.items()
        if pv.is_tidy_few_function(v[1].decode("utf-8", "ignore"))
    }
    fps = [
        (key, sv.measured_record(tidy[key][1].decode("utf-8", "ignore")))
        for key in pv.pick_by_hash(tidy, pr.FP_COUNT, pr.FP_PER_ORIGIN)
    ]
    monos = []
    candidates = pr.multi_function_pool(pool)
    for key in pv.pick_by_hash(candidates, pr.MONO_COUNT * 3, pr.MONO_PER_ORIGIN):
        if len(monos) == pr.MONO_COUNT:
            break
        original = candidates[key][1].decode("utf-8", "ignore")
        mono = pr._safe_inline(original)
        orig = sv.measured_record(original)
        lo, hi = pr.MONO_TOKENS
        if mono is None or not lo <= orig["tokens"] <= hi:
            continue
        record = sv.measured_record(mono)
        if len(record["functions"]) == 1:
            monos.append((key, orig, record))
    return {"tidy": fps, "monos": monos}


def load_extra(args: argparse.Namespace) -> dict[str, Any]:
    if args.extra.exists():
        return pickle.loads(args.extra.read_bytes())  # noqa: S301
    extra = build_extra(args.cache, ir.DEFAULT_CACHE)
    args.extra.write_bytes(pickle.dumps(extra))
    return extra


class Scored:
    """All score tables for one candidate."""

    def __init__(
        self,
        items: Mapping[str, float],
        tidy: Sequence[float],
        mono: Sequence[float],
        orig: Sequence[float],
    ) -> None:
        self.items, self.tidy, self.mono, self.orig = items, tidy, mono, orig


def score_all(
    cand: dg.Candidate, p0: int | None, prep: Mapping[str, Any], ctx: dg.Context
) -> Scored:
    def score(p: Mapping[str, dg.Prepared], key: Any) -> float:
        return dg.gated_score(p[key], cand, ctx)

    return Scored(
        {k: dg.gated_score(p, cand, ctx) for k, p in prep["items"][p0].items()},
        [score(prep["tidy"][p0], i) for i in range(len(prep["tidy"][p0]))],
        [score(prep["mono"][p0], i) for i in range(len(prep["mono"][p0]))],
        [score(prep["orig"][p0], i) for i in range(len(prep["orig"][p0]))],
    )


def direction(
    s: Scored,
    items: Sequence[ss.Item],
    problems: Sequence[str],
    fit: Sequence[int],
    held: Sequence[int],
    functions: Sequence[int],
) -> dict[str, Any]:
    """Metrics when the ``fit`` tidy modules join the good items."""
    extra = [s.tidy[i] for i in fit]
    kinds = ss.kinds_of(items)
    glob = ss.cut_line([*ss.pick(s.items, ss.keys_of(items, "good")), *extra])
    folds = []
    for p in problems:
        parts = ss.split_for_problem(items, problems, p)
        cut = ss.cut_line([*ss.pick(s.items, parts["train"]["good"]), *extra])
        test = parts["test"]
        folds.append(
            {
                "cut": cut,
                "good": ss.pick(s.items, test["good"]),
                "worse": ss.pick(s.items, test["worse"]),
                "mono": ss.pick(s.items, test["contested"]),
                "kind_counts": ss.kind_counts(s.items, test["worse"], kinds, cut),
                "mono_flagged": sum(
                    v < cut - ss.EPS for v in ss.pick(s.items, test["contested"])
                ),
            }
        )
    held_flag = [i for i in held if s.tidy[i] < glob - ss.EPS]
    return {
        "cut": glob,
        "cv": scr.cv_summary_of(folds),
        "tidy_held": len(held),
        "tidy_flagged": len(held_flag),
        "single_held": sum(functions[i] == 1 for i in held),
        "single_flagged": sum(functions[i] == 1 for i in held_flag),
        "mech_flagged": sum(v < glob - ss.EPS for v in s.mono) / len(s.mono),
        "extra_cut_28": ss.cut_line(ss.pick(s.items, ss.keys_of(items, "good"))),
    }


def combine(
    dirs: Sequence[Mapping[str, Any]], s: Scored, items: Sequence[ss.Item]
) -> dict[str, Any]:
    good = ss.pick(s.items, ss.keys_of(items, "good"))
    mean = statistics.fmean
    kinds = dirs[0]["cv"]["by_kind"]
    held_n = sum(d["tidy_held"] for d in dirs)
    single_n = sum(d["single_held"] for d in dirs)
    return {
        "cut": mean(d["cut"] for d in dirs),
        "cut_28_only": dirs[0]["extra_cut_28"],
        "tidy_flagged": sum(d["tidy_flagged"] for d in dirs) / held_n,
        "tidy_flagged_by_dir": [d["tidy_flagged"] / d["tidy_held"] for d in dirs],
        "single_flagged": sum(d["single_flagged"] for d in dirs) / max(1, single_n),
        "auc_worse": dirs[0]["cv"]["auc_worse"],
        "auc_school": dirs[0]["cv"]["auc_mono"],
        "school_flagged": mean(d["cv"]["mono_sens"] for d in dirs),
        "mech_flagged": mean(d["mech_flagged"] for d in dirs),
        "auc_mech": ss.good_above_auc(good, s.mono),
        "by_kind": {k: mean(d["cv"]["by_kind"][k] for d in dirs) for k in kinds},
        "sens": mean(d["cv"]["sens"] for d in dirs),
        "drops": scr.paired_drops(s.items, items),
        "mech_drop": statistics.fmean(
            o - m for o, m in zip(s.orig, s.mono, strict=True)
        ),
    }


def regressions(row: Mapping[str, Any], ref: Mapping[str, Any]) -> list[str]:
    return [k for k, v in row["by_kind"].items() if v < ref["by_kind"][k] - 1e-9]


def accepted(row: Mapping[str, Any], ref: Mapping[str, Any]) -> bool:
    return (
        row["tidy_flagged"] <= 0.10
        and row["school_flagged"] >= 0.60
        and row["mech_flagged"] >= 0.60
        and row["auc_worse"] >= 0.80
        and not regressions(row, ref)
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    items, _, records, problems = pickle.loads(args.cache.read_bytes())  # noqa: S301
    extra = load_extra(args)
    base = bm.load_calibration(bm.DEFAULT_CALIBRATION)
    tidy = extra["tidy"]
    prep: dict[str, Any] = {"items": {}, "tidy": {}, "mono": {}, "orig": {}}
    for p0 in (None, 2):
        prep["items"][p0] = {k: dg.prepare(r, base, p0) for k, r in records.items()}
        prep["tidy"][p0] = [dg.prepare(r, base, p0) for _, r in tidy]
        prep["mono"][p0] = [dg.prepare(m, base, p0) for _, _, m in extra["monos"]]
        prep["orig"][p0] = [dg.prepare(o, base, p0) for _, o, _ in extra["monos"]]
    good_prep = [prep["items"][2][k] for k in ss.keys_of(items, "good")]
    ctx = dg.make_context(base, good_prep)
    order = sorted(range(len(tidy)), key=lambda i: pv.content_key(tidy[i][0].encode()))
    half_a, half_b = order[0::2], order[1::2]
    functions = [len(r["functions"]) for _, r in tidy]
    rows = {}
    for cand in (PLACEHOLDER, *dg.CANDIDATES):
        s = score_all(cand, None if cand is PLACEHOLDER else 2, prep, ctx)
        dirs = [
            direction(s, items, problems, a, b, functions)
            for a, b in ((half_a, half_b), (half_b, half_a))
        ]
        rows[cand.name] = combine(dirs, s, items)
    ref = rows["placeholder"]
    for name, row in rows.items():
        row["regressions"] = regressions(row, ref)
        row["accepted"] = name != "placeholder" and accepted(row, ref)
    return {
        "rows": rows,
        "context": {"phi": ctx.phi, "c0": ctx.c0, "size_n": ctx.size_n},
        "tidy_halves": [[tidy[i][0] for i in half_a], [tidy[i][0] for i in half_b]],
        "n": {
            "good": len(ss.keys_of(items, "good")),
            "tidy": len(tidy),
            "mech": len(extra["monos"]),
            "worse": len(ss.keys_of(items, "worse")),
            "school": len(ss.keys_of(items, "contested")),
        },
    }


def pct(v: float | None) -> str:
    return "-" if v is None else f"{100 * v:.0f}%"


def num(v: float | None, d: int = 2) -> str:
    return "-" if v is None else f"{v:.{d}f}"


def report_text(r: Mapping[str, Any]) -> str:
    rows = r["rows"]
    lines = [
        f"Dominance gating candidates (no model call); n={r['n']}; gate context {r['context']}",
        "candidate | cut(28+20 tidy) | cut(28) | heldout tidy flagged | single-fn tidy flagged | AUC good>worse | school AUC/flagged | mech AUC/flagged | sens@90 | regressions vs placeholder | accept",
    ]
    for name, x in rows.items():
        lines.append(
            f"{name} | {num(x['cut'], 1)} | {num(x['cut_28_only'], 1)} | {pct(x['tidy_flagged'])} "
            f"({', '.join(pct(v) for v in x['tidy_flagged_by_dir'])}) | {pct(x['single_flagged'])} | "
            f"{num(x['auc_worse'])} | {num(x['auc_school'])}/{pct(x['school_flagged'])} | "
            f"{num(x['auc_mech'])}/{pct(x['mech_flagged'])} | {pct(x['sens'])} | "
            f"{','.join(x['regressions']) or 'none'} | {'YES' if x['accepted'] else 'no'}"
        )
    kinds = list(next(iter(rows.values()))["by_kind"])
    lines += [
        "",
        "sensitivity at 90% specificity per type",
        "candidate | " + " | ".join(kinds),
    ]
    lines += [
        f"{n} | " + " | ".join(pct(x["by_kind"][k]) for k in kinds)
        for n, x in rows.items()
    ]
    lines += [
        "",
        "paired drop (agreed minus variant, points); monolith = school drafts; mech = original minus mechanical monolith",
    ]
    dk = list(next(iter(rows.values()))["drops"])
    lines.append("candidate | " + " | ".join(dk) + " | mech")
    lines += [
        f"{n} | "
        + " | ".join(num(x["drops"][k], 1) for k in dk)
        + f" | {num(x['mech_drop'], 1)}"
        for n, x in rows.items()
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--extra", type=Path, required=True)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-txt", type=Path)
    args = parser.parse_args(argv)
    result = run(args)
    text = report_text(result)
    if args.out_json:
        args.out_json.write_text(
            json.dumps(result, indent=1, sort_keys=True, default=str)
        )
    if args.out_txt:
        args.out_txt.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
