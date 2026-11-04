"""Does the end-to-end top-line score separate known-good from known-worse code?

Scores the labelled sets of ``discrimination_run`` (4 agreed solutions + 24 proxy
modules as good, 27 mechanical degradations as worse, 11 monolithic school
drafts as contested) with the placeholder calibration, reports the cut line
and per-type sensitivity, then compares bench-only calibration variants by
leave-one-problem-out cross-validation. No model call; deterministic.

    uv run python score_separation_run.py --run-state <dir>... \
        [--out-json result.json] [--out-txt report.txt]
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_run as ir
import baseline_measure as bm
import baseline_protocol as bp
import baseline_rank_run as rr
import discrimination_run as drun
import refactor_line_eval as rle
import score_separation as ss
import score_variants as sv

CUTS = tuple(range(50, 100, 5))
# Real home even when test-env.sh redirects HOME to a scratch directory.
USER_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
PLAN_NOTES = (
    USER_HOME
    / "source/agent-memory/projects/varde-py/working/plans"
    / "2026-10-31-vqs-example-baseline/notes/run-state"
)
USER_CACHE = USER_HOME / ".cache/varde/bench"
RUN_STATE_DIRS = sorted(PLAN_NOTES.iterdir()) if PLAN_NOTES.is_dir() else []
PROXIES = 24


# ---- loading ----------------------------------------------------------------


def blob_files(cache: Path, per_repo: int, repos: Sequence[Path]) -> list:
    """(rows, source) per sampled corpus and reference file, as in load_reference."""
    manifest = json.loads(ir.MANIFEST.read_text())
    found: list = []
    for repo in manifest["repositories"]:
        if repo["status"] != "verified" or "Python" not in repo["languages"]:
            continue
        checkout, sha = cache / repo["name"].replace("/", "__"), repo["pin_sha"]
        listing = ir.git_out(checkout, "ls-tree", "-r", "--name-only", sha)
        blobs = (
            ir.git_out(checkout, "show", f"{sha}:{p}")
            for p in ir.sample_paths(listing.decode().splitlines(), per_repo * 3)
        )
        found += within_limits(blobs, per_repo)
    for repo in repos:
        paths = ir.sample_paths(rr.listed_paths(repo), per_repo * 3)
        blobs = ((repo / p).read_bytes() for p in paths if (repo / p).is_file())
        found += within_limits(blobs, per_repo)
    return found


def within_limits(blobs: Any, per_repo: int) -> list:
    kept = [b for b in blobs if ir.MIN_BYTES <= len(b) <= ir.MAX_BYTES][:per_repo]
    return [
        (bm.raw_measure_sources({"module.py": b}, "python")["functions"], b.decode())
        for b in kept
    ]


def proxy_sources(files: Sequence) -> dict[str, str]:
    by_digest = {drun.digest(rows): source for rows, source in files}
    picked = drun.pick_proxies([rows for rows, _ in files], PROXIES)
    return {f"proxy:{drun.digest(r)[:8]}": by_digest[drun.digest(r)] for r in picked}


def monolith_sources(run_states: Sequence[Path]) -> dict[str, str]:
    """Single-function drafts of the decomposition-sensitive problems."""
    found: dict[str, str] = {}
    for run_dir in sorted(run_states):
        for path in sorted(run_dir.glob("python__*__write-*.txt")):
            match = ir.DRAFT_FILE.match(path.name)
            code = bp.extract_code(path.read_text()) if match else None
            if not (match and code) or match["problem"] not in drun.MONOLITHIC_PROBLEMS:
                continue
            if len(ir.rows_of_source(code)) == 1:
                found[f"{match['problem']}/{run_dir.name}/{match['school']}"] = code
    return found


def build_items(
    agreed: Mapping[str, str],
    proxies: Mapping[str, str],
    degraded: Mapping[str, Mapping[str, str]],
    drafts: Mapping[str, str],
) -> tuple[list[ss.Item], dict[str, str]]:
    items = [ss.Item(f"agreed:{p}", "good", p) for p in agreed]
    items += [ss.Item(k, "good") for k in proxies]
    items += [
        ss.Item(f"{kind}:{p}", "worse", p, kind)
        for kind, by_problem in degraded.items()
        for p in by_problem
    ]
    items += [ss.Item(f"draft:{k}", "contested", k.split("/")[0]) for k in drafts]
    sources = {f"agreed:{p}": s for p, s in agreed.items()} | dict(proxies)
    sources |= {
        f"{kind}:{p}": s for kind, bp_ in degraded.items() for p, s in bp_.items()
    }
    sources |= {f"draft:{k}": s for k, s in drafts.items()}
    return items, sources


# ---- scoring ----------------------------------------------------------------


def shipped_scores(
    sources: Mapping[str, str], calibration: Any = None
) -> dict[str, float]:
    """The end-to-end path: ``score_source`` with the default calibration."""
    return {
        k: bm.score_source(s, "python", calibration)["score"]
        for k, s in sources.items()
    }


def candidate_tables(
    records: Mapping[str, Mapping[str, Any]], variants: Sequence[sv.Variant]
) -> dict[str, dict[str, float]]:
    base = bm.load_calibration(bm.DEFAULT_CALIBRATION)
    tables = {}
    for variant in variants:
        calibration = sv.calibrated(base, variant)
        tables[variant.name] = {
            k: sv.score_of(r, calibration, variant.gate) for k, r in records.items()
        }
    return tables


def set_view(scores: ss.Scores, items: Sequence[ss.Item]) -> dict[str, Any]:
    """Headline numbers of one score table over all labelled items."""
    good = ss.pick(scores, ss.keys_of(items, "good"))
    worse = ss.pick(scores, ss.keys_of(items, "worse"))
    mono = ss.pick(scores, ss.keys_of(items, "contested"))
    cut = ss.cut_line(good)
    agreed = {
        i.key.removeprefix("agreed:"): scores[i.key]
        for i in items
        if i.key.startswith("agreed:")
    }
    variants = {
        kind: {i.key.split(":", 1)[1]: scores[i.key] for i in items if i.kind == kind}
        for kind in sorted({i.kind for i in items if i.kind})
    }
    paired = ss.paired_deltas(agreed, variants)
    return {
        "sets": {
            "good": ss.summary(good),
            "agreed": ss.summary(list(agreed.values())),
            "worse": ss.summary(worse),
            "contested": ss.summary(mono),
        },
        "auc_good_worse": ss.good_above_auc(good, worse),
        "auc_good_monolith": ss.good_above_auc(good, mono),
        "cut": cut,
        "sens_worse": ss.flagged_share(worse, cut),
        "sens_monolith": ss.flagged_share(mono, cut),
        "sens_by_kind": ss.sensitivity_by_kind(scores, items, cut),
        "mean_score_by_kind": {
            k: ss.summary(list(v.values()))["mean"] for k, v in variants.items()
        },
        "cut_table": ss.cut_table(scores, items, CUTS),
        "paired": paired,
        "monotonic_share": ss.overall_drop_share(paired),
    }


def confidence_counts(
    items: Sequence[ss.Item], records: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, int]]:
    """role -> structure_confidence -> count, over the measured records."""
    counts: dict[str, Counter] = {}
    for item in items:
        confidence = str(records[item.key]["structure_confidence"])
        counts.setdefault(item.role, Counter())[confidence] += 1
    return {role: dict(c) for role, c in counts.items()}


def candidate_row(
    name: str, scores: ss.Scores, items: Sequence[ss.Item]
) -> dict[str, Any]:
    got = ss.evaluate(
        scores,
        ss.keys_of(items, "good"),
        ss.keys_of(items, "worse"),
        ss.keys_of(items, "contested"),
    )
    return {"name": name, **got}


# ---- report -----------------------------------------------------------------


def pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.0f}%"


def num(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def view_lines(title: str, view: Mapping[str, Any]) -> list[str]:
    lines = [title, "set | n | mean | min | max"]
    for name, s in view["sets"].items():
        lines.append(
            f"{name} | {s['n']} | {num(s['mean'], 1)} | {num(s['min'], 1)} | "
            f"{num(s['max'], 1)}"
        )
    lines += [
        (
            f"AUC good>worse {num(view['auc_good_worse'])} | "
            f"AUC good>monolith {num(view['auc_good_monolith'])}"
        ),
        (
            f"cut line (>=90% of good at/above): {num(view['cut'], 1)} | "
            f"worse flagged {pct(view['sens_worse'])} | "
            f"monolith flagged {pct(view['sens_monolith'])}"
        ),
        "sensitivity by type: "
        + ", ".join(f"{k}={pct(v)}" for k, v in view["sens_by_kind"].items()),
        "mean score by type: "
        + ", ".join(f"{k}={num(v, 1)}" for k, v in view["mean_score_by_kind"].items()),
        "paired agreed-minus-variant (mean delta, monotonic share): "
        + ", ".join(
            f"{k}={num(sum(p['deltas'].values()) / max(len(p['deltas']), 1), 1)}"
            f"/{pct(p['monotonic'])}"
            for k, p in view["paired"].items()
        )
        + f" | overall monotonic {pct(view['monotonic_share'])}",
        "cut | good kept | worse flagged | monolith flagged",
    ]
    lines += [
        f"{r['cut']} | {pct(r['good_kept'])} | {pct(r['worse_flagged'])} | "
        f"{pct(r['contested_flagged'])}"
        for r in view["cut_table"]
    ]
    return lines


def fold_lines(title: str, folds: Sequence[Mapping[str, Any]]) -> list[str]:
    total = ss.pooled(folds)
    lines = [title, "held-out | chosen | AUC | cut | sens | monolith sens"]
    lines += [
        f"{f['held_out']} | {f.get('chosen', '-')} | {num(f['auc'])} | "
        f"{num(f['cut'], 1)} | {pct(f['sens'])} | {pct(f['contested_sens'])}"
        for f in folds
    ]
    lines.append(
        f"pooled | AUC {num(total['auc'])} | sens@90 {pct(total['sens'])} | "
        f"monolith {pct(total['contested_sens'])} | "
        f"mean cut {num(total['mean_cut'], 1)}"
    )
    lines.append(
        "pooled sensitivity by type: "
        + ", ".join(f"{k}={pct(v)}" for k, v in total["by_kind"].items())
    )
    return lines


def candidate_lines(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = ["candidate (in-sample, all items) | AUC | cut | sens@90 | monolith"]
    lines += [
        f"{r['name']} | {num(r['auc'])} | {num(r['cut'], 1)} | {pct(r['sens'])} | "
        f"{pct(r['contested_sens'])}"
        for r in rows
    ]
    return lines


def report_text(payload: Mapping[str, Any]) -> str:
    lines = [
        "Top-line score separation report (no model call)",
        f"sizes: {json.dumps(payload['sizes'], sort_keys=True)}",
        (
            "scope: score_scope over one file record; a file's score comes from "
            "its summed function and file costs per 1000 tokens (token-weighted "
            "combine across files in a multi-file scope, not per function)."
        ),
        "",
        *view_lines("A. shipped path (score_source, facts only)", payload["shipped"]),
        "",
        *view_lines(
            "B. scan-equivalent (measures merged), placeholder", payload["scan"]
        ),
        "",
        *fold_lines("CV: placeholder, shipped path (A)", payload["cv_shipped"]),
        "",
        *fold_lines("CV: placeholder, measured (B)", payload["cv_default"]),
        "",
        *fold_lines("CV: selected by train AUC", payload["cv_selected"]),
        "",
        *view_lines(
            f"C. most-chosen candidate {payload['most_chosen']} (in-sample view)",
            payload["chosen_view"],
        ),
        "",
        *candidate_lines(payload["ablations"]),
        "",
        *candidate_lines(payload["candidates"]),
        "",
        "structure_confidence of measured records: "
        + json.dumps(payload["structure_confidence"], sort_keys=True),
    ]
    return "\n".join(lines)


def labelled(args: argparse.Namespace) -> tuple[list[ss.Item], dict[str, str]]:
    repos = args.reference_repos
    if repos is None:
        repos = [rr.REFERENCE_ROOT / name for name in rr.DEFAULT_REFERENCE]
    files = blob_files(args.cache, args.per_repo, [r for r in repos if r.is_dir()])
    agreed = {
        p.parent.parent.name: p.read_text()
        for p in sorted(ir.AGREED_ROOT.glob("*/python/solution.py"))
    }
    return build_items(
        agreed,
        proxy_sources(files),
        drun.degraded_sources(agreed),
        monolith_sources(args.run_state),
    )


def check_line(args: argparse.Namespace) -> int:
    """Refactor line and monolith advisory over the labelled sets."""
    items, sources = labelled(args)
    calibration = bm.load_calibration(args.calibration)
    scores = shipped_scores(sources, calibration)
    limits = rle.limits_for(args.calibration)
    ok, lines = rle.line_report(items, scores, rle.advisory_flags(sources, limits))
    print("\n".join(lines))
    return 0 if ok else 1


def run(args: argparse.Namespace) -> dict[str, Any]:
    items, sources = labelled(args)
    problems = sorted(
        i.key.removeprefix("agreed:") for i in items if i.key.startswith("agreed:")
    )
    variants = sv.candidates()
    records = {k: sv.measured_record(s) for k, s in sources.items()}
    tables = candidate_tables(records, variants)
    ablation = candidate_tables(records, sv.ablations())
    order = [v.name for v in variants]
    default = sv.Variant("placeholder", "x1", "gated").name
    shipped = shipped_scores(sources)
    selected = ss.lopo_selected(tables, order, items, problems)
    chosen = Counter(f["chosen"] for f in selected)
    most_chosen = max(order, key=lambda n: (chosen[n], -order.index(n)))
    return {
        "sizes": {
            "good": len(ss.keys_of(items, "good")),
            "worse": len(ss.keys_of(items, "worse")),
            "contested": len(ss.keys_of(items, "contested")),
            "candidates": len(order),
        },
        "shipped": set_view(shipped, items),
        "scan": set_view(tables[default], items),
        "cv_shipped": ss.lopo_fixed(shipped, items, problems),
        "cv_default": ss.lopo_fixed(tables[default], items, problems),
        "cv_selected": selected,
        "most_chosen": most_chosen,
        "chosen_view": set_view(tables[most_chosen], items),
        "candidates": [candidate_row(n, tables[n], items) for n in order],
        "ablations": [candidate_row(n, t, items) for n, t in ablation.items()],
        "structure_confidence": confidence_counts(items, records),
        "scores": {"shipped": shipped, "scan": tables[default]},
        "proxy_ids": sorted(k for k in sources if k.startswith("proxy:")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-state", type=Path, nargs="+", default=RUN_STATE_DIRS)
    parser.add_argument("--check-line", action="store_true")
    parser.add_argument("--calibration", type=Path, default=bm.DEFAULT_CALIBRATION)
    parser.add_argument("--cache", type=Path, default=USER_CACHE)
    parser.add_argument("--per-repo", type=int, default=40)
    parser.add_argument("--reference-repos", type=Path, nargs="*")
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-txt", type=Path)
    args = parser.parse_args(argv)
    if args.check_line:
        return check_line(args)
    payload = run(args)
    text = report_text(payload)
    if args.out_json:
        args.out_json.write_text(json.dumps(payload, sort_keys=True, indent=1))
    if args.out_txt:
        args.out_txt.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
