# ruff: noqa: E501, S112  (report text templates, skipped inputs)
"""Deterministic evaluation of the delta verdict (no model calls, dev split only).

    uv run python delta_eval_run.py --check
    uv run python delta_eval_run.py --reference-stability

Pools are the dev-split files of the 9 repo styles that ``region_sim`` uses, with
the 7 degradation types plus the monolith, the school drafts and the curated
mined pairs. Scores are the product scores (cal-1 through the user view).
Nothing is tuned: a miss against a bar is reported with its numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_run as ir
import baseline_rank_run as rr
import delta_eval as de
import region_sim as rs
import score_separation_run as ssr
from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.reference import CALIBRATION, N_MIN, score_of_facts

GOOD_FP_BAR = 0.12
OUT_DEFAULT = (
    ssr.USER_HOME
    / "source/agent-memory/projects/varde-py/working/plans"
    / "2026-10-31-vqs-delta-and-measures/notes/delta-eval.md"
)
K1_SEEDS = 50


class RepoFile(NamedTuple):
    path: str
    source: str
    score: float


class PairScore(NamedTuple):
    repo: str
    path: str
    before: float
    after: float
    dev: bool


def make_scorer() -> Any:
    calibration = load_calibration(CALIBRATION)

    def score(source: str, path: str = "module.py") -> float | None:
        try:
            return score_of_facts(extract_facts(source, "python", path), calibration)
        except Exception:  # noqa: BLE001 - a source the extractor rejects is skipped
            return None

    return score


# ---- loading (I/O) ----------------------------------------------------------


def read_repo(
    repo: str, paths: Sequence[str], read: Any, per_repo: int, score: Any
) -> list[RepoFile]:
    """Up to ``per_repo`` scored dev files; ``dev_paths`` yields dev paths only."""
    files: list[RepoFile] = []
    for path in rs.dev_paths(repo, paths):
        if len(files) >= per_repo:
            break
        de.require_dev(f"{repo}:{path}", rs.split_of)
        blob = read(path)
        if blob is None or not ir.MIN_BYTES <= len(blob) <= ir.MAX_BYTES:
            continue
        if rs.measure_file(blob) is None:
            continue
        source = blob.decode("utf-8", "replace")
        value = score(source, path)
        if value is not None:
            files.append(RepoFile(path, source, value))
    return files


def load_repos(args: argparse.Namespace, score: Any) -> dict[str, list[RepoFile]]:
    repos: dict[str, list[RepoFile]] = {}
    manifest = json.loads(ir.MANIFEST.read_text())
    for repo in manifest["repositories"]:
        if repo["status"] != "verified" or "Python" not in repo["languages"]:
            continue
        checkout, sha = args.cache / repo["name"].replace("/", "__"), repo["pin_sha"]
        if not checkout.is_dir():
            continue
        paths = (
            ir.git_out(checkout, "ls-tree", "-r", "--name-only", sha)
            .decode()
            .splitlines()
        )
        files = read_repo(
            repo["name"], paths, rs.git_reader(checkout, sha), args.per_repo, score
        )
        if len(files) >= rs.MIN_DEV_FILES:
            repos[repo["name"]] = files
    for root in args.reference_repos:
        if not root.is_dir():
            continue
        name = f"ref/{root.name}"
        files = read_repo(
            name, rr.listed_paths(root), rs.file_reader(root), args.per_repo, score
        )
        if len(files) >= rs.MIN_DEV_FILES:
            repos[name] = files
    return repos


def degraded_sources(source: str) -> dict[str, str]:
    """The degradation and monolith texts of one source that differ from it."""
    import pd2_validation as pv
    import quality_degrade as qd

    makers: dict[str, Any] = dict(qd.DEGRADATIONS)
    makers["monolith"] = pv.inline_to_monolith
    unchanged = qd.identity(source)
    found: dict[str, str] = {}
    for kind, make in makers.items():
        try:
            text = make(source)
        except Exception:  # noqa: BLE001 - degradations that cannot apply are skipped
            continue
        if text is not None and text != unchanged:
            found[kind] = text
    return found


def load_pair_sources(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Curated mined pairs with before and after sources (same filters as region_sim)."""
    import mined_pairs_curated as cur
    import mined_pairs_run as mpr

    found = []
    for pair in (p for p in mpr.load_pairs() if cur.commit_ok(p, 5, cur.INCLUDE)):
        path = pair["changed_files"][0]
        clone = args.cache / pair["repo"].replace("/", "__")
        if not clone.is_dir():
            continue
        before = mpr.read_blob(clone, pair["parent_sha"], path)
        after = mpr.read_blob(clone, pair["child_sha"], path)
        if before is None or after is None:
            continue
        if not (mpr.parses(before) and mpr.parses(after)):
            continue
        tokens = [mpr.sv.measured_record(s)["tokens"] for s in (before, after)]
        if tokens[0] < 1000 or abs(tokens[1] - tokens[0]) > 0.4 * tokens[0]:
            continue
        found.append(
            {
                "repo": pair["repo"],
                "path": path,
                "before": before,
                "after": after,
            }
        )
    return found


def load_drafts(args: argparse.Namespace) -> tuple[dict[str, str], int]:
    """School drafts of dev-split problems, and how many drafts exist in all."""
    drafts = ssr.monolith_sources(args.run_state)
    dev = {
        key: code
        for key, code in drafts.items()
        if rs.split_of(key.split("/")[0]) == de.DEV
    }
    return dev, len(drafts)


# ---- evaluation -------------------------------------------------------------


def reference_for(
    files: Sequence[RepoFile], mode: str, index: int, small: int
) -> list[float]:
    """Leave-one-out reference of file ``index``; ``ref12`` uses the first ``small``."""
    scores = [f.score for f in files]
    if mode == "ref12":
        scores = scores[:small]
    return de.leave_one_out(scores, index)


def eval_files(
    files: Sequence[RepoFile], mode: str, variant_files: int, score: Any
) -> dict[str, Any]:
    """Per kind: [worse-than-before, below-p10, newly-below] flags; plus good files."""
    limit = variant_files if mode == "ref12" else len(files)
    good_below, good_product = [], []
    kinds: dict[str, dict[str, list[bool]]] = {}
    deltas: dict[str, list[float]] = {}
    for index, file in enumerate(files[:limit]):
        reference = reference_for(files, mode, index, variant_files)
        original_below = de.below_p10(file.score, reference)
        good_below.append(original_below)
        if len(reference) >= N_MIN:
            good_product.append(original_below)
        if index >= variant_files:
            continue
        for kind, text in degraded_sources(file.source).items():
            value = score(text, file.path)
            if value is None:
                continue
            cell = kinds.setdefault(kind, {"worse": [], "below": [], "new": []})
            below = de.below_p10(value, reference)
            cell["worse"].append(de.worse_than_before(value, file.score))
            cell["below"].append(below)
            cell["new"].append(below and not original_below)
            deltas.setdefault(kind, []).append(value - file.score)
    return {
        "good_below": good_below,
        "good_product": good_product,
        "kinds": kinds,
        "deltas": deltas,
    }


def merge_eval(parts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    good: list[bool] = []
    product: list[bool] = []
    kinds: dict[str, dict[str, list[bool]]] = {}
    deltas: dict[str, list[float]] = {}
    for part in parts:
        good += part["good_below"]
        product += part["good_product"]
        for kind, cell in part["kinds"].items():
            into = kinds.setdefault(kind, {"worse": [], "below": [], "new": []})
            for key, flags in cell.items():
                into[key] += flags
        for kind, values in part["deltas"].items():
            deltas.setdefault(kind, []).extend(values)
    return {
        "good_below": de.tally(good),
        "good_product": de.tally(product),
        "kinds": {
            kind: {key: de.tally(flags) for key, flags in cell.items()}
            for kind, cell in sorted(kinds.items())
        },
        "deltas": deltas,
    }


def score_pairs(
    pairs: Sequence[Mapping[str, Any]], score: Any
) -> tuple[list[PairScore], int]:
    scored = []
    for pair in pairs:
        before, after = (
            score(pair["before"], pair["path"]),
            score(pair["after"], pair["path"]),
        )
        if before is None or after is None:
            continue
        dev = rs.split_of(f"{pair['repo']}:{pair['path']}") == de.DEV
        scored.append(PairScore(pair["repo"], pair["path"], before, after, dev))
    return scored, len(pairs) - len(scored)


def eval_pairs(
    scored: Sequence[PairScore], repos: Mapping[str, Sequence[RepoFile]]
) -> dict[str, Any]:
    """Before -> after verdicts; refactor-after files are the good side."""
    worse, before_below, after_below, closer = [], [], [], []
    no_reference = 0
    for pair in scored:
        worse.append(de.worse_than_before(pair.after, pair.before))
        files = repos.get(pair.repo)
        if files is None:
            no_reference += 1
            continue
        reference = [f.score for f in files if f.path != pair.path]
        before_out = de.below_p10(pair.before, reference)
        before_below.append(before_out)
        after_below.append(de.below_p10(pair.after, reference))
        if before_out:
            closer.append(pair.after > pair.before)
    return {
        "worse_than_before": de.tally(worse),
        "before_below_p10": de.tally(before_below),
        "after_below_p10": de.tally(after_below),
        "improved_among_before_below": de.tally(closer),
        "no_reference": no_reference,
        "deltas": [p.after - p.before for p in scored],
    }


def eval_drafts(
    drafts: Mapping[str, str], repos: Mapping[str, Sequence[RepoFile]], score: Any
) -> dict[str, Any]:
    flags = []
    for code in drafts.values():
        value = score(code)
        if value is None:
            continue
        flags += [
            de.below_p10(value, [f.score for f in files]) for files in repos.values()
        ]
    return {"below_p10": de.tally(flags), "drafts": len(drafts)}


def eval_k1(
    repos: Mapping[str, Sequence[RepoFile]], pairs: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Repo-calibrated k=1 region versus the default regions on the same pairs."""
    import baseline_region as br

    pools = {}
    for name, files in repos.items():
        measured = [rs.measure_file(f.source.encode()) for f in files]
        pools[name] = rs.build_pool(name, [m for m in measured if m is not None], 0)
    corpus: dict[str, list[int]] = {m: [] for m in rs.MEASURES}
    for pool in pools.values():
        for rows in pool.rows:
            for m in rs.MEASURES:
                corpus[m] += br.example_values(rows, m)
    defaults = rs.default_regions(rs.placeholder_region(), corpus)
    value_pairs = [
        {
            "repo": p["repo"],
            "before": [
                tuple(r[m] or 0 for m in rs.MEASURES)
                for r in ir.rows_of_source(p["before"])
            ],
            "after": [
                tuple(r[m] or 0 for m in rs.MEASURES)
                for r in ir.rows_of_source(p["after"])
            ],
        }
        for p in pairs
    ]
    out = {}
    for name, default in defaults.items():
        runs = {
            pool.name: rs.run_pool(pool, default, corpus, [1], K1_SEEDS)
            for pool in pools.values()
        }
        out[name] = rs.pair_view(value_pairs, runs, rs.region_vector(default), [1])
    return out


# ---- report -----------------------------------------------------------------


def num(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def kind_lines(result: Mapping[str, Any]) -> list[str]:
    lines = [
        "type | worse than before (circular) | below reference p10 (leave-one-out) | newly below p10 (original was not)",
        "--- | --- | --- | ---",
    ]
    for kind, cell in result["kinds"].items():
        lines.append(
            f"{kind} | {de.fmt(cell['worse'])} | {de.fmt(cell['below'])} | {de.fmt(cell['new'])}"
        )
    return lines


def mode_lines(title: str, result: Mapping[str, Any]) -> list[str]:
    good = result["good_below"]
    return [
        f"### {title}",
        "",
        f"- Good (unchanged) files below leave-one-out reference p10: {de.fmt(good)}",
        f"- Of these, files whose leave-one-out reference has at least {N_MIN} files (the product's minimum): {de.fmt(result['good_product'])}",
        f"- Good files worse than before: 0% (0/{good['n']}, n={good['n']}) by construction (a file is never worse than itself)",
        "",
        *kind_lines(result),
        "",
    ]


def pair_lines(pairs: Mapping[str, Any], total: int, skipped: int) -> list[str]:
    deltas = de.distribution(pairs["deltas"])
    return [
        f"- Pairs scored: n={deltas['n']} of {total} curated pairs ({skipped} unscorable); no repo reference for {pairs['no_reference']}",
        f"- Refactor-after worse than before (false positive on good files): {de.fmt(pairs['worse_than_before'])} of {total} pairs",
        f"- Before below repo reference p10: {de.fmt(pairs['before_below_p10'])}; after below p10: {de.fmt(pairs['after_below_p10'])}",
        f"- Among before-below-p10 pairs, after scores higher: {de.fmt(pairs['improved_among_before_below'])}",
        f"- Score delta (after - before) over n={deltas['n']}: min {num(deltas['min'])}, p10 {num(deltas['p10'])}, p25 {num(deltas['p25'])}, median {num(deltas['median'])}, p75 {num(deltas['p75'])}, p90 {num(deltas['p90'])}, max {num(deltas['max'])}",
    ]


def tolerance_lines(
    table: Sequence[Mapping[str, Any]], proposal: float | None, n_dev: int
) -> list[str]:
    kinds = sorted(table[0]["flagged"]) if table else []
    lines = [
        f"Good side: refactor-after files of dev-hash mined pairs (n={n_dev}). Detection side: degradations of the dev files (circular vs their own originals).",
        "",
        "tolerance (points) | good-file false positive | " + " | ".join(kinds),
        "--- | --- | " + " | ".join("---" for _ in kinds),
    ]
    for row in table:
        flagged = " | ".join(de.fmt(row["flagged"][k]) for k in kinds)
        lines.append(f"{row['tolerance']:.1f} | {de.fmt(row['good'])} | {flagged}")
    verdict = (
        f"Proposed tolerance: {proposal:.1f} points (smallest with good-file false positive at or under {de.TOLERANCE_FP_TARGET:.0%}); chosen on dev-hash pairs only and NOT applied to the product."
        if proposal is not None
        else f"No tolerance in {de.TOLERANCES} brings the good-file false positive to {de.TOLERANCE_FP_TARGET:.0%}; none proposed."
    )
    return [*lines, "", verdict]


def k1_lines(k1: Mapping[str, Any], own: Mapping[str, Any]) -> list[str]:
    lines = [
        "region | after no further outside | before outside | strictly closer (of outside)",
        "--- | --- | --- | ---",
    ]
    for name, view in k1.items():
        for label, cell in (
            (
                f"repo-calibrated k=1 (from {name} default)",
                view["repo_calibrated_by_k"][1],
            ),
            (f"{name} default region", view["default_region"]),
        ):
            lines.append(
                f"{label} | {rs.pct(cell['no_further_outside'])} | {rs.pct(cell['before_outside'])} | {rs.pct(cell['strictly_closer_among_outside'])}"
            )
    lines.append(
        f"own reference line (p10 of the repo's file scores) | - | before below p10 {de.fmt(own['before_below_p10'])} | after scores higher, of before-below: {de.fmt(own['improved_among_before_below'])}"
    )
    return lines


def render(results: Mapping[str, Any]) -> list[str]:
    pairs, pairs_dev, drafts = results["pairs"], results["pairs_dev"], results["drafts"]
    sizes = ", ".join(
        f"{name} n={len(files)}" for name, files in results["sizes"].items()
    )
    return [
        "# Delta verdict evaluation (deterministic, no model calls)",
        "",
        "Dev split only: files come from `splits.assignments` dev paths; thresholds and the tolerance proposal were chosen on dev split data only, and the test split (`splits.lock`) is never read. Nothing is tuned to meet a bar.",
        "",
        f"Repo styles: {len(results['sizes'])} ({sizes}). Scores are product scores (cal-1, user view).",
        "",
        "Reading guide: comparing a degradation with its own unmodified file is circular (any degradation that moves the score is a drop; unchanged files are never worse, so that false-positive rate is 0 by construction). Do not read the worse-than-before flag rates as detection accuracy. The leave-one-out reference comparison (file excluded from its own reference) is the non-circular column.",
        "",
        "## Degradations and good files",
        "",
        *mode_lines(
            "Reference of the first 12 files per repo (leave-one-out n=11; p10 is one file, so the 10% rate holds only in expectation)",
            results["ref12"],
        ),
        *mode_lines(
            "Reference of all dev files loaded per repo (leave-one-out, larger n)",
            results["full"],
        ),
        "## School drafts (monolithic, dev-split problems)",
        "",
        f"- Below the repo reference p10 (draft x repo): {de.fmt(drafts['below_p10'])}; drafts used: n={drafts['drafts']} of {results['drafts_total']} (the rest belong to problems outside the dev split and are not read)",
        "",
        "## Mined before -> after pairs (should mostly be not worse)",
        "",
        "All curated pairs (the same set region_sim uses):",
        "",
        *pair_lines(pairs, results["pairs_total"], results["pairs_unscorable"]),
        "",
        f"Dev-hash pairs only (`repo:path` falls in the dev split; n={pairs_dev['worse_than_before']['n']} of {results['pairs_total']}):",
        "",
        *pair_lines(pairs_dev, results["pairs_total"], 0),
        "",
        "## Materiality tolerance (proposal only)",
        "",
        *tolerance_lines(
            results["tolerance"],
            results["proposal"],
            pairs_dev["worse_than_before"]["n"],
        ),
        "",
        "## k=1 default region versus own-reference line (curated pairs)",
        "",
        f"Region rows use n of pair x resample ({K1_SEEDS} seeds); t12 reported repo-calibrated 57-64% strictly closer against 70% for the default.",
        "",
        *k1_lines(results["k1"], pairs),
        "",
        "## Bar",
        "",
        *bar_lines(results),
        "",
        "## Caveats",
        "",
        "- Small reference: with n=11 the p10 line is one file and its sampling sd is about 23 points (n=20: 12, n=50: 7; see `--reference-stability`), so single-repo verdicts are noisy; N_MIN is 20.",
        "- Good-file false positives here are measured on the repos' own dev files, which are not curated as good; they are the repo's typical files.",
        "- Detection rates against degradations are partly circular (see the reading guide); only the leave-one-out and pair columns are independent of the file's own score.",
    ]


def bar_lines(results: Mapping[str, Any]) -> list[str]:
    lines = []
    for label, cell in (
        (f"reference n >= {N_MIN} (product regime)", results["full"]["good_product"]),
        ("reference n=11 (below the product minimum)", results["ref12"]["good_below"]),
    ):
        met = cell["rate"] is not None and cell["rate"] <= GOOD_FP_BAR
        lines.append(
            f"- Good-file below-p10 false-positive rate, {label}: {de.fmt(cell)}; bar {GOOD_FP_BAR:.2f}: {'met' if met else 'MISSED'}"
        )
    return lines


def good_fp_problems(results: Mapping[str, Any]) -> list[str]:
    """The bar applies where the product gives a verdict (reference n >= N_MIN).

    The n=11 mode is reported but sits below the product minimum, so a miss
    there is printed as a note and does not fail the check.
    """
    cell = results["full"]["good_product"]
    if cell["rate"] is not None and cell["rate"] > GOOD_FP_BAR:
        return [f"good-file below-p10 rate {de.fmt(cell)} over bar {GOOD_FP_BAR}"]
    return []


def evaluate(
    args: argparse.Namespace, repos: Mapping[str, Sequence[RepoFile]], score: Any
) -> dict[str, Any]:
    ref12 = merge_eval(
        [eval_files(f, "ref12", args.variant_files, score) for f in repos.values()]
    )
    full = merge_eval(
        [eval_files(f, "full", args.variant_files, score) for f in repos.values()]
    )
    pair_sources = load_pair_sources(args)
    scored, unscorable = score_pairs(pair_sources, score)
    pairs = eval_pairs(scored, repos)
    pairs_dev = eval_pairs([p for p in scored if p.dev], repos)
    table = de.tolerance_table(pairs_dev["deltas"], ref12["deltas"])
    drafts, total = load_drafts(args)
    return {
        "sizes": dict(repos),
        "ref12": ref12,
        "full": full,
        "pairs": pairs,
        "pairs_dev": pairs_dev,
        "pairs_total": len(pair_sources),
        "pairs_unscorable": unscorable,
        "tolerance": table,
        "proposal": de.propose_tolerance(table),
        "drafts": eval_drafts(drafts, repos, score),
        "drafts_total": total,
        "k1": eval_k1(repos, pair_sources),
    }


def stability_lines(repos: Mapping[str, Sequence[RepoFile]]) -> list[str]:
    lines = []
    for name, files in repos.items():
        scores = [f.score for f in files]
        line = de.reference_line(scores)
        spreads = ", ".join(
            f"sd@{s}={num(de.p10_spread(scores, s)['sd'])} (n={de.p10_spread(scores, s)['n']} draws)"
            for s in de.STABILITY_SIZES
        )
        lines.append(f"{name}: p10 line {num(line)} n={len(scores)} files; {spreads}")
    return lines


def plan_out(path: Path) -> Path:
    out = rs.plan_path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--reference-stability", action="store_true")
    parser.add_argument("--split", default=de.DEV, help="only dev is readable")
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--per-repo", type=int, default=60)
    parser.add_argument("--variant-files", type=int, default=12)
    parser.add_argument("--cache", type=Path, default=ssr.USER_CACHE)
    parser.add_argument("--run-state", type=Path, nargs="+", default=ssr.RUN_STATE_DIRS)
    parser.add_argument(
        "--reference-repos",
        type=Path,
        nargs="*",
        default=[
            ssr.USER_HOME / "source/reference-repos" / n for n in rr.DEFAULT_REFERENCE
        ],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.split != de.DEV:
        print(
            f"refusing to read the {args.split} split: only dev is readable",
            file=sys.stderr,
        )
        return 2
    score = make_scorer()
    repos = load_repos(args, score)
    if args.reference_stability:
        print("\n".join(stability_lines(repos)))
        return 0
    results = evaluate(args, repos, score)
    lines = render(results)
    plan_out(args.out).write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if not args.check:
        return 0
    problems = [*de.missing_n(lines), *good_fp_problems(results)]
    print("check: " + ("ok" if not problems else f"FAIL {problems}"))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
