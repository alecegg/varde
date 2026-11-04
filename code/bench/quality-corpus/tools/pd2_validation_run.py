# ruff: noqa: E501  (report text templates)
"""Validate the P+D2 candidate on modules it was not designed on (no model call).

    uv run python pd2_validation_run.py --cache items.pkl [--out-json r.json] [--out-txt r.txt]

False positives: tidy few-function modules from the verified corpus and the
reference repos. Monoliths: real multi-function modules merged into one function.
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
import pd2_validation as pv
import score_separation as ss
import score_variants as sv
import scorer_candidates as sc

PLACEHOLDER = sc.Spec("placeholder")
PD2 = sc.Spec("P+D2", p0=2, dominance=2.0)
PER_REPO_READ = 150
FP_COUNT, FP_PER_ORIGIN = 40, 5
MONO_COUNT, MONO_PER_ORIGIN = 14, 2
MONO_TOKENS = (250, 1500)


def corpus_pool(cache: Path) -> dict[str, tuple[str, bytes]]:
    """Path-hash sample of every verified Python corpus repo, read at its pin."""
    manifest = json.loads(ir.MANIFEST.read_text())
    pool: dict[str, tuple[str, bytes]] = {}
    for repo in manifest["repositories"]:
        if repo["status"] != "verified" or "Python" not in repo["languages"]:
            continue
        checkout, sha = cache / repo["name"].replace("/", "__"), repo["pin_sha"]
        listing = ir.git_out(checkout, "ls-tree", "-r", "--name-only", sha)
        for path in ir.sample_paths(listing.decode().splitlines(), PER_REPO_READ):
            blob = ir.git_out(checkout, "show", f"{sha}:{path}")
            pool[f"{repo['name']}:{path}"] = (repo["name"], blob)
    return pool


def reference_pool() -> dict[str, tuple[str, bytes]]:
    pool: dict[str, tuple[str, bytes]] = {}
    for repo in sorted(p for p in rr.REFERENCE_ROOT.iterdir() if p.is_dir()):
        for path in ir.sample_paths(rr.listed_paths(repo), PER_REPO_READ):
            file = repo / path
            if file.is_file():
                pool[f"ref/{repo.name}:{path}"] = (
                    f"ref/{repo.name}",
                    file.read_bytes(),
                )
    return pool


def usable(pool: Mapping[str, tuple[str, bytes]], used: set[str]) -> dict:
    """Decodable, size-bounded files not already used as proxies or drafts."""
    out = {}
    for key, (origin, blob) in pool.items():
        fits = ir.MIN_BYTES <= len(blob) <= ir.MAX_BYTES
        if fits and pv.content_key(blob) not in used:
            out[key] = (origin, blob)
    return out


def file_metrics(record: Mapping[str, Any], source: str) -> dict[str, Any]:
    fns = record["functions"]
    return {
        "functions": len(fns),
        "tokens": record["tokens"],
        "max_cognitive": max((f.get("cognitive") or 0 for f in fns), default=0),
        "max_tokens": max((f.get("tokens") or 0 for f in fns), default=0),
        "nesting": pv.max_nesting(source),
    }


def score_pair(record: Mapping[str, Any], base: Any) -> tuple[float, float]:
    return sc.candidate_score(record, base, PLACEHOLDER), sc.candidate_score(
        record, base, PD2
    )


def select_false_positives(pool: Mapping, base: Any) -> list[dict[str, Any]]:
    tidy = {
        k: v
        for k, v in pool.items()
        if pv.is_tidy_few_function(v[1].decode("utf-8", "ignore"))
    }
    rows = []
    for key in pv.pick_by_hash(tidy, FP_COUNT, FP_PER_ORIGIN):
        source = tidy[key][1].decode("utf-8", "ignore")
        record = sv.measured_record(source)
        p, d = score_pair(record, base)
        rows.append(
            {"key": key, "placeholder": p, "pd2": d, **file_metrics(record, source)}
        )
    return rows


def multi_function_pool(pool: Mapping) -> dict:
    found = {}
    for key, (origin, blob) in pool.items():
        mono = _safe_inline(blob.decode("utf-8", "ignore"))
        if mono is not None:
            found[key] = (origin, blob)
    return found


def _safe_inline(source: str) -> str | None:
    try:
        return pv.inline_to_monolith(source)
    except SyntaxError, ValueError, RecursionError:
        return None


def build_monoliths(pool: Mapping, base: Any) -> list[dict[str, Any]]:
    rows = []
    candidates = multi_function_pool(pool)
    for key in pv.pick_by_hash(candidates, MONO_COUNT * 3, MONO_PER_ORIGIN):
        if len(rows) == MONO_COUNT:
            break
        original = candidates[key][1].decode("utf-8", "ignore")
        mono = _safe_inline(original)
        orig_record = sv.measured_record(original)
        lo, hi = MONO_TOKENS
        if mono is None or not lo <= orig_record["tokens"] <= hi:
            continue
        record = sv.measured_record(mono)
        if len(record["functions"]) != 1:
            continue
        rows.append(
            {
                "key": key,
                "original": score_pair(orig_record, base),
                "mono": score_pair(record, base),
                "original_functions": len(orig_record["functions"]),
                "mono_tokens": record["tokens"],
                "mono_cognitive": record["functions"][0].get("cognitive") or 0,
            }
        )
    return rows


def cuts_of(
    scores: Mapping[str, float], items: Sequence[ss.Item], problems: Sequence[str]
) -> dict[str, Any]:
    good = ss.pick(scores, ss.keys_of(items, "good"))
    folds = [
        ss.cut_line(
            ss.pick(scores, ss.split_for_problem(items, problems, p)["train"]["good"])
        )
        for p in problems
    ]
    return {
        "global": ss.cut_line(good),
        "folds": folds,
        "bootstrap": pv.cut_bootstrap(good, ss.cut_line),
    }


def share_below(values: Sequence[float], cut: float) -> float:
    return ss.flagged_share(values, cut) or 0.0


def fp_summary(
    rows: Sequence[Mapping], field: str, cut: float, good: Sequence[float]
) -> dict[str, Any]:
    values = [r[field] for r in rows]
    flagged = [r for r in rows if r[field] < cut - ss.EPS]
    return {
        "n": len(rows),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "flagged": len(flagged),
        "flagged_metric_poor": sum(pv.metric_poor(r) for r in flagged),
        "metric_clean": sum(pv.metric_clean(r) for r in rows),
        "flagged_metric_clean": sum(pv.metric_clean(r) for r in flagged),
        "single_function": sum(r["functions"] == 1 for r in rows),
        "flagged_single_function": sum(r["functions"] == 1 for r in flagged),
        "cut_with_false_positives_as_good": ss.cut_line([*good, *values])
        if good
        else None,
        "flagged_keys": [r["key"] for r in flagged],
    }


def monolith_table(
    good: Mapping[str, Sequence[float]],
    groups: Mapping[str, Mapping[str, Sequence[float]]],
    cuts: Mapping[str, float],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label, by_scorer in groups.items():
        out[label] = {
            name: {
                "n": len(by_scorer[name]),
                "auc": ss.good_above_auc(good[name], by_scorer[name]),
                "flagged": share_below(by_scorer[name], cuts[name]),
                "mean": statistics.fmean(by_scorer[name]),
            }
            for name in by_scorer
        }
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    items, sources, records, problems = pickle.loads(args.cache.read_bytes())  # noqa: S301
    base = bm.load_calibration(bm.DEFAULT_CALIBRATION)
    specs = {"placeholder": PLACEHOLDER, "pd2": PD2}
    tables = {
        name: {k: sc.candidate_score(r, base, spec) for k, r in records.items()}
        for name, spec in specs.items()
    }
    used = {pv.content_key(s.encode()) for s in sources.values()}
    pool = usable({**corpus_pool(args.bench_cache), **reference_pool()}, used)
    fps = select_false_positives(pool, base)
    monos = build_monoliths(pool, base)
    cuts = {n: cuts_of(t, items, problems) for n, t in tables.items()}
    draft_keys = ss.keys_of(items, "contested")
    good = {n: ss.pick(t, ss.keys_of(items, "good")) for n, t in tables.items()}
    groups = {
        "school drafts": {n: ss.pick(t, draft_keys) for n, t in tables.items()},
        "mechanical": {
            "placeholder": [r["mono"][0] for r in monos],
            "pd2": [r["mono"][1] for r in monos],
        },
    }
    groups["all"] = {
        n: groups["school drafts"][n] + groups["mechanical"][n] for n in tables
    }
    gcut = {n: c["global"] for n, c in cuts.items()}
    return {
        "pool_size": len(pool),
        "cuts": cuts,
        "false_positives": {
            n: fp_summary(fps, n, gcut[n], good[n]) for n in ("placeholder", "pd2")
        },
        "fp_rows": fps,
        "monoliths": monolith_table(good, groups, gcut),
        "mono_rows": monos,
        "paired_original_minus_mono": {
            n: statistics.fmean(r["original"][i] - r["mono"][i] for r in monos)
            for i, n in enumerate(("placeholder", "pd2"))
        },
        "good_n": len(good["pd2"]),
    }


def fmt(v: float | None, d: int = 1) -> str:
    return "-" if v is None else f"{v:.{d}f}"


def report_text(r: Mapping[str, Any]) -> str:
    lines = [
        "P+D2 validation on unseen modules (no model call; code/bench/quality-corpus/tools/pd2_validation*.py)",
        f"candidate pool (hash-sampled readable files): {r['pool_size']}; good set n={r['good_n']}",
        "",
        "Cut line (90% of the 28 good items kept; folds = leave-one-problem-out training cuts)",
    ]
    for n, c in r["cuts"].items():
        b = c["bootstrap"]
        lines.append(
            f"{n}: global {fmt(c['global'])}; folds {', '.join(fmt(x) for x in c['folds'])}; "
            f"bootstrap mean {fmt(b['mean'])} sd {fmt(b['sd'])} range {fmt(b['min'])}-{fmt(b['max'])}"
        )
    lines += ["", "False positives: tidy 1-3 function modules (not asserted good)"]
    for n, s in r["false_positives"].items():
        lines.append(
            f"{n}: n={s['n']} mean {fmt(s['mean'])} median {fmt(s['median'])} min {fmt(s['min'])} "
            f"flagged {s['flagged']} (metric-poor among flagged {s['flagged_metric_poor']}; "
            f"metric-clean {s['flagged_metric_clean']}/{s['metric_clean']} flagged; "
            f"single-function {s['flagged_single_function']}/{s['single_function']} flagged); "
            f"cut if these joined the good set {fmt(s['cut_with_false_positives_as_good'])}"
        )
    flagged = [
        x for x in r["fp_rows"] if x["pd2"] < r["cuts"]["pd2"]["global"] - ss.EPS
    ]
    lines.append(
        "flagged by P+D2 (key | placeholder -> P+D2 | fns, tokens, max cognitive, max fn tokens, nesting):"
    )
    for x in flagged:
        lines.append(
            f"  {x['key']} | {fmt(x['placeholder'])} -> {fmt(x['pd2'])} | {x['functions']}, "
            f"{x['tokens']}, {x['max_cognitive']}, {x['max_tokens']}, {x['nesting']}"
        )
    lines += [
        "",
        "Mechanical monoliths built from: "
        + "; ".join(x["key"] for x in r["mono_rows"]),
    ]
    lines += ["", "Monoliths: AUC good>monolith, share below cut, mean score"]
    for label, by in r["monoliths"].items():
        for n, m in by.items():
            lines.append(
                f"{label} {n}: n={m['n']} AUC {fmt(m['auc'], 2)} flagged {fmt(100 * m['flagged'], 0)}% mean {fmt(m['mean'])}"
            )
    lines.append(
        "mechanical paired drop (original module minus its monolith, points): "
        + ", ".join(f"{n} {fmt(v)}" for n, v in r["paired_original_minus_mono"].items())
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--bench-cache", type=Path, default=ir.DEFAULT_CACHE)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-txt", type=Path)
    args = parser.parse_args(argv)
    result = run(args)
    text = report_text(result)
    if args.out_json:
        args.out_json.write_text(json.dumps(result, indent=1, sort_keys=True))
    if args.out_txt:
        args.out_txt.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
