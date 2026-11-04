# ruff: noqa: E501, S112  (report text templates, skipped inputs)
"""File-level features and robust whole-distribution fits (experiment only).

    uv run python region_fit_experiment.py --out notes/file-features.json \
        [--tables notes/file-features-tables.md] [--check]

Deterministic, no model call, no score or schema change. Part B reports
``file_features`` per repo style (spread, detection of the 7 degradations, the
school drafts and the curated mined pairs). Part C compares the t11 q90 anchor
with robust fits (median plus scaled MAD, Tukey fence, per-file median of q90,
trimmed q90) on threshold stability and held-out acceptance. The constants are
local to this file; ``baseline_region.py`` defaults are not edited.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_run as ir
import baseline_measure as bm
import baseline_rank_run as rr
import baseline_region as br
import file_features as ff
import region_sim as rs
import score_separation as ss

METHODS = ("q90", "mad3", "tukey", "file_q90", "trim_q90")
MAD_SCALE_X10000 = 14826  # 1.4826 * MAD estimates sigma for normal data
MAD_MULTIPLE = 3
TRIM_PERCENT = 5
ANCHOR_PERCENTILE = 90


# ---- Part C: anchors and fits (pure) ----------------------------------------


def mad_anchor(values: Sequence[int]) -> int | None:
    """Median + 3 * scaled MAD (integer arithmetic)."""
    mid = br.nearest_rank(values, 50)
    if mid is None:
        return None
    mad = br.nearest_rank([abs(v - mid) for v in values], 50) or 0
    return mid + (MAD_MULTIPLE * MAD_SCALE_X10000 * mad + 5000) // 10000


def tukey_anchor(values: Sequence[int]) -> int | None:
    """Third quartile + 1.5 * IQR."""
    q1, q3 = br.nearest_rank(values, 25), br.nearest_rank(values, 75)
    if q1 is None or q3 is None:
        return None
    return q3 + (3 * (q3 - q1) + 1) // 2


def trimmed_anchor(values: Sequence[int]) -> int | None:
    """Anchor percentile after dropping the top 5% of values."""
    ordered = sorted(values)
    kept = ordered[: len(ordered) - len(ordered) * TRIM_PERCENT // 100]
    return br.nearest_rank(kept, ANCHOR_PERCENTILE)


def per_file_anchor(per_file: Sequence[Sequence[int]]) -> int | None:
    """Median over files of each file's own anchor percentile."""
    anchors = [br.nearest_rank(v, ANCHOR_PERCENTILE) for v in per_file if v]
    return br.nearest_rank([a for a in anchors if a is not None], 50)


def anchor(method: str, per_file: Sequence[Sequence[int]]) -> int | None:
    pooled = [v for values in per_file for v in values]
    if method == "q90":
        return br.nearest_rank(pooled, ANCHOR_PERCENTILE)
    if method == "mad3":
        return mad_anchor(pooled)
    if method == "tukey":
        return tukey_anchor(pooled)
    if method == "file_q90":
        return per_file_anchor(per_file)
    if method == "trim_q90":
        return trimmed_anchor(pooled)
    raise ValueError(f"unknown method: {method}")


def fit_region(
    default: Mapping[str, int],
    examples: Sequence[Sequence[Mapping[str, Any]]],
    corpus: Mapping[str, Sequence[int]],
    method: str,
    pull: bool,
) -> dict[str, int]:
    """Threshold set from k example files; ``pull`` blends toward the default."""
    region = dict(sorted(default.items()))
    k = len(examples)
    for measure, key in br.FITTED.items():
        per_file = [br.example_values(sample, measure) for sample in examples]
        found = anchor(method, per_file)
        if key not in region or k <= 0 or found is None:
            continue
        value = br.shifted(region[key], found, k) if pull else found
        bounds = br.corpus_bounds(list(corpus.get(measure, ())))
        region[key] = value if bounds is None else min(max(value, bounds[0]), bounds[1])
    return region


def method_runs(
    pools: Sequence[rs.Pool],
    default: Mapping[str, int],
    corpus: Mapping[str, Sequence[int]],
    ks: Sequence[int],
    seeds: int,
    fit: tuple[str, bool],
) -> dict[str, dict[int, list[rs.Run]]]:
    method, pull = fit
    out: dict[str, dict[int, list[rs.Run]]] = {}
    for pool in pools:
        out[pool.name] = {}
        for k in ks:
            runs = []
            for seed in range(seeds):
                drawn = rs.draw(len(pool.rows), k, seed)
                region = fit_region(
                    default, [pool.rows[i] for i in drawn], corpus, method, pull
                )
                runs.append(rs.Run(seed, tuple(drawn), rs.region_vector(region)))
            out[pool.name][k] = runs
    return out


def balanced(cell: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    """good accepted + mean flagged over the degradation kinds - 1 (Youden-like)."""
    good = cell.get(f"{prefix}good_heldout")
    flags = [
        v["value"]
        for label, v in cell.items()
        if label.startswith(f"{prefix}flagged:")
        and label != f"{prefix}flagged:school_draft"
        and isinstance(v, dict)
        and v["value"] is not None
    ]
    if not good or good["value"] is None or not flags:
        return {"n": len(flags), "value": None}
    return {
        "n": good["n"],
        "value": ff.round6(good["value"] + sum(flags) / len(flags) - 1),
    }


def method_summary(
    pools: Sequence[rs.Pool],
    runs: Mapping[str, Mapping[int, list[rs.Run]]],
    default_vector: Sequence[int],
    drafts: Sequence[rs.Variant],
    ks: Sequence[int],
    scoring: rs.Scoring | None,
) -> dict[str, Any]:
    stability = rs.stability_view(runs, ks)
    accept = rs.accept_views(pools, runs, default_vector, drafts, ks, scoring)
    by_k = accept["repo_calibrated_by_k"]
    return {
        "overall_median_spread": stability["overall_median_spread"],
        "smallest_k_at_or_below_10pct": stability["smallest_k_at_or_below_10pct"][
            "overall"
        ],
        "median_spread_by_key": stability["median_spread"],
        "accepted_by_k": by_k,
        "balanced_strict": {k: balanced(by_k[k], "") for k in ks},
        "balanced_scored": {k: balanced(by_k[k], "scored:") for k in ks},
    }


def fit_comparison(
    data: Loaded,
    defaults: Mapping[str, Mapping[str, int]],
    ks: Sequence[int],
    seeds: int,
    scoring_cfg: tuple[rs.Scorer, int, int],
) -> dict[str, Any]:
    scorer, score_seeds, cross_files = scoring_cfg
    out: dict[str, Any] = {}
    for default_name, default in defaults.items():
        vector = rs.region_vector(default)
        scores = [scorer(item, vector) for p in data.pools for item in p.items]
        scoring = rs.Scoring(scorer, ss.cut_line(scores), score_seeds, cross_files)
        cells: dict[str, Any] = {"refactor_line": rs.stat(scoring.line, len(scores))}
        for method in METHODS:
            for pull in (True, False):
                runs = method_runs(
                    data.pools, default, data.corpus, ks, seeds, (method, pull)
                )
                label = f"{method}:{'shifted' if pull else 'raw'}"
                cells[label] = method_summary(
                    data.pools,
                    runs,
                    vector,
                    data.drafts,
                    ks,
                    scoring if pull else None,
                )
        out[default_name] = cells
    return out


# ---- Part B: assembly (pure) ------------------------------------------------


class Loaded(NamedTuple):
    pools: list[rs.Pool]
    file_rows: dict[str, list[list[dict[str, Any]]]]  # repo -> file -> full rows
    variant_rows: dict[str, dict[int, dict[str, list[dict[str, Any]]]]]
    draft_rows: list[list[dict[str, Any]]]
    drafts: list[rs.Variant]
    pairs: list[dict[str, Any]]  # repo, before, after (full rows)
    corpus: dict[str, list[int]]
    skipped: dict[str, int]


def feature_values(
    rows_by_repo: Mapping[str, Sequence[Sequence[Mapping[str, Any]]]], name: str
) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for repo, files in sorted(rows_by_repo.items()):
        values = [ff.file_features(rows)[name] for rows in files if rows]
        out[repo] = [v for v in values if v is not None]
    return out


def variant_rows_for(data: Loaded, name: str) -> list[ff.VariantRow]:
    found: list[ff.VariantRow] = []
    for repo, by_file in sorted(data.variant_rows.items()):
        for index, kinds in sorted(by_file.items()):
            base = ff.file_features(data.file_rows[repo][index])[name]
            for kind, rows in sorted(kinds.items()):
                found.append(
                    ff.VariantRow(repo, kind, base, ff.file_features(rows)[name])
                )
    found += [
        ff.VariantRow(None, "school_draft", None, ff.file_features(rows)[name])
        for rows in data.draft_rows
    ]
    for pair in data.pairs:
        before = ff.file_features(pair["before"])[name]
        after = ff.file_features(pair["after"])[name]
        found.append(ff.VariantRow(pair["repo"], "mined_before", None, before))
        found.append(ff.VariantRow(pair["repo"], "mined_after", before, after))
    return found


def features_report(data: Loaded) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in ff.FEATURES:
        report = ff.feature_report(
            feature_values(data.file_rows, name), variant_rows_for(data, name)
        )
        report["source"] = ff.SOURCE_OF[name]
        out[name] = report
    return out


def baseline_from_sim(path: Path) -> dict[str, Any]:
    """Function-level baseline (placeholder default) from notes/sim-users.json."""
    sim = json.loads(path.read_text())["by_default"]["placeholder"]
    cell = sim["held_out_and_variants"]["default_region"]
    ratios: dict[str, Any] = {}
    for k, entry in sim["style"].items():
        known = [
            v["between_over_within"]["value"]
            for v in entry.values()
            if v["between_over_within"]["value"] is not None
        ]
        ratios[k] = rs.stat(ff.median(known), len(known))
    return {
        "good_accepted_scored": cell["scored:good_heldout"],
        "flagged_scored": {
            label.removeprefix("scored:flagged:"): value
            for label, value in sorted(cell.items())
            if label.startswith("scored:flagged:")
        },
        "median_between_over_within_by_k": ratios,
    }


# ---- loading (I/O) ----------------------------------------------------------


def measure_full(blob: bytes) -> rs.SimFile | None:
    """Like ``region_sim.measure_file`` but keeps every raw measure column."""
    import score_variants as sv

    source = blob.decode("utf-8", "replace")
    try:
        rows = bm.raw_measure_sources({"module.py": blob}, "python")["functions"]
        return rs.SimFile(source, [dict(r) for r in rows], sv.measured_record(source))
    except Exception:  # noqa: BLE001 - a file the parser rejects is skipped
        return None


def read_full_files(
    repo: str, paths: Sequence[str], read: Callable[[str], bytes | None], per_repo: int
) -> list[rs.SimFile]:
    files: list[rs.SimFile] = []
    for path in rs.dev_paths(repo, paths):
        if len(files) >= per_repo:
            break
        blob = read(path)
        if blob is None or not ir.MIN_BYTES <= len(blob) <= ir.MAX_BYTES:
            continue
        measured = measure_full(blob)
        if measured is not None:
            files.append(measured)
    return files


def degraded_texts(source: str) -> dict[str, str]:
    """Degraded and monolith variants of one source that changed it."""
    import pd2_validation as pv
    import quality_degrade as qd

    makers: dict[str, Callable[[str], str | None]] = dict(qd.DEGRADATIONS)
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


def variants_of(
    source: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, rs.Variant]]:
    import score_variants as sv

    rows_by_kind: dict[str, list[dict[str, Any]]] = {}
    items: dict[str, rs.Variant] = {}
    for kind, text in degraded_texts(source).items():
        try:
            rows = ir.rows_of_source(text)
            items[kind] = (rs.peak_vector(rows), sv.measured_record(text))
        except Exception:  # noqa: BLE001 - unmeasurable variants are skipped
            continue
        rows_by_kind[kind] = rows
    return rows_by_kind, items


def add_repo(
    loaded: dict[str, Any],
    name: str,
    files: Sequence[rs.SimFile],
    variant_files: int,
) -> None:
    rows = [f.rows for f in files]
    variants: dict[int, dict[str, rs.Variant]] = {}
    variant_rows: dict[int, dict[str, list[dict[str, Any]]]] = {}
    for i in range(min(variant_files, len(files))):
        variant_rows[i], variants[i] = variants_of(files[i].source)
    loaded["pools"].append(
        rs.Pool(
            name,
            [rs.trim(r) for r in rows],
            [rs.peak_vector(r) for r in rows],
            [f.record for f in files],
            variants,
        )
    )
    loaded["file_rows"][name] = rows
    loaded["variant_rows"][name] = variant_rows


def load_all(args: argparse.Namespace) -> Loaded:
    loaded: dict[str, Any] = {
        "pools": [],
        "file_rows": {},
        "variant_rows": {},
    }
    skipped: dict[str, int] = {}
    corpus: dict[str, list[int]] = {m: [] for m in rs.MEASURES}

    def take(name: str, files: Sequence[rs.SimFile]) -> None:
        for file in files:
            for m in rs.MEASURES:
                corpus[m] += br.example_values(file.rows, m)
        if len(files) >= rs.MIN_DEV_FILES:
            add_repo(loaded, name, files, args.variant_files)
        else:
            skipped[name] = len(files)

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
        take(
            repo["name"],
            read_full_files(
                repo["name"], paths, rs.git_reader(checkout, sha), args.per_repo
            ),
        )
    for root in args.reference_repos:
        if root.is_dir():
            name = f"ref/{root.name}"
            take(
                name,
                read_full_files(
                    name, rr.listed_paths(root), rs.file_reader(root), args.per_repo
                ),
            )
    drafts, draft_rows = load_drafts(args.run_state)
    return Loaded(
        loaded["pools"],
        loaded["file_rows"],
        loaded["variant_rows"],
        draft_rows,
        drafts,
        load_pair_rows(),
        corpus,
        skipped,
    )


def load_drafts(
    run_states: Sequence[Path],
) -> tuple[list[rs.Variant], list[list[dict[str, Any]]]]:
    import score_separation_run as ssr
    import score_variants as sv

    items, rows_list = [], []
    for _, code in sorted(ssr.monolith_sources(run_states).items()):
        rows = ir.rows_of_source(code)
        items.append((rs.peak_vector(rows), sv.measured_record(code)))
        rows_list.append(rows)
    return items, rows_list


def load_pair_rows() -> list[dict[str, Any]]:
    """Curated mined pairs with the full rows of both sides."""
    import mined_pairs_curated as cur
    import mined_pairs_run as mpr
    import score_separation_run as ssr

    found = []
    for pair in (p for p in mpr.load_pairs() if cur.commit_ok(p, 5, cur.INCLUDE)):
        path = pair["changed_files"][0]
        clone = ssr.USER_CACHE / pair["repo"].replace("/", "__")
        if not clone.is_dir():
            continue
        before = mpr.read_blob(clone, pair["parent_sha"], path)
        after = mpr.read_blob(clone, pair["child_sha"], path)
        if (
            before is None
            or after is None
            or not (mpr.parses(before) and mpr.parses(after))
        ):
            continue
        tokens = [mpr.sv.measured_record(s)["tokens"] for s in (before, after)]
        if tokens[0] < 1000 or abs(tokens[1] - tokens[0]) > 0.4 * tokens[0]:
            continue
        found.append(
            {
                "repo": pair["repo"],
                "before": ir.rows_of_source(before),
                "after": ir.rows_of_source(after),
            }
        )
    return found


# ---- report -----------------------------------------------------------------


def pct(node: Mapping[str, Any] | None) -> str:
    if not node or node["value"] is None:
        return "-"
    return f"{100 * node['value']:.0f}% (n={node['n']})"


def num(node: Mapping[str, Any] | None) -> str:
    if not node or node["value"] is None:
        return "-"
    return f"{node['value']:.2f} (n={node['n']})"


def detection_cell(report: Mapping[str, Any] | None) -> str:
    if report is None:
        return "-"
    best = ff.best_tail(report)
    if best is None:
        return "-"
    tail, cell = best
    repo = report["repo_cut"][tail]
    return f"{tail[0].upper()} {pct(cell)} / repo {pct(repo)}"


def render_features(result: Mapping[str, Any]) -> list[str]:
    features = result["features"]
    kinds = sorted({k for f in features.values() for k in f["kinds"]})
    base = result["baseline"]
    lines = [
        "### Spread between repo styles (k-sample median statistic, ratio = between/within)",
        "",
        "feature | source | raw ratio | k=1 | k=3 | k=6 | repo share of variance",
        "--- | --- | --- | --- | --- | --- | ---",
    ]
    for name, f in features.items():
        sampled = f["sampled_ratio"]
        lines.append(
            f"{name} | {f['source']} | {num({'n': f['spread']['n'], 'value': f['spread']['ratio']})} | "
            f"{num({'n': sampled['1']['n'], 'value': sampled['1']['ratio']})} | "
            f"{num({'n': sampled['3']['n'], 'value': sampled['3']['ratio']})} | "
            f"{num({'n': sampled['6']['n'], 'value': sampled['6']['ratio']})} | {pct(f['repo_variance_share'])}"
        )
    ratios = base["median_between_over_within_by_k"]
    lines += [
        f"function-level baseline (median over keys) | existing | - | {num(ratios['1'])} | {num(ratios['3'])} | {num(ratios['6'])} | -",
        "",
        "### Detection at the 10th/90th-percentile-of-good cut (best tail H=above p90, L=below p10; pooled cut / repo cut)",
        "",
        "feature | good flagged (L/H) | " + " | ".join(kinds),
        "--- | --- | " + " | ".join("---" for _ in kinds),
    ]
    for name, f in features.items():
        flagged = f["good_flagged"]
        good = (
            "-"
            if flagged is None
            else f"{pct(flagged['low'])} / {pct(flagged['high'])}"
        )
        cells = " | ".join(detection_cell(f["kinds"].get(kind)) for kind in kinds)
        lines.append(f"{name} | {good} | {cells}")
    flagged = base["flagged_scored"]
    lines.append(
        "function-level baseline (placeholder default, scored; good accepted "
        f"{pct(base['good_accepted_scored'])}) | - | "
        + " | ".join(pct(flagged.get(k)) for k in kinds)
    )
    return [*lines, ""]


def render_fits(result: Mapping[str, Any], ks: Sequence[int]) -> list[str]:
    lines = []
    for default_name, cells in result["fits"].items():
        lines += [
            f"### Fits, default region {default_name} (refactor line {num(cells['refactor_line'])})",
            "",
            "method | form | "
            + " | ".join(f"spread k={k}" for k in ks)
            + " | smallest k at <=10% | good accepted k=3 (strict / scored) | balanced strict k=3 | balanced scored k=3",
            "--- | --- | " + " | ".join("---" for _ in ks) + " | --- | --- | --- | ---",
        ]
        for label, cell in cells.items():
            if label == "refactor_line":
                continue
            method, form = label.split(":")
            spreads = " | ".join(num(cell["overall_median_spread"][str(k)]) for k in ks)
            at3 = cell["accepted_by_k"]["3"]
            lines.append(
                f"{method} | {form} | {spreads} | {cell['smallest_k_at_or_below_10pct']} | "
                f"{pct(at3.get('good_heldout'))} / {pct(at3.get('scored:good_heldout'))} | "
                f"{num(cell['balanced_strict']['3'])} | {num(cell['balanced_scored']['3'])}"
            )
        lines.append("")
    return lines


def render(result: Mapping[str, Any]) -> str:
    ks = result["ks"]
    head = [
        "## Part B: file-level features",
        "",
        f"Repos: {json.dumps(result['repos'], sort_keys=True)}; school drafts n={result['n_drafts']}; curated pairs n={result['n_pairs']}.",
        "",
    ]
    fits = ["## Part C: robust fits", "", *render_fits(result, ks)]
    return "\n".join([*head, *render_features(result), *fits]) + "\n"


def dumps(result: Mapping[str, Any]) -> str:
    return json.dumps(result, indent=1, sort_keys=True) + "\n"


def analyse(
    data: Loaded,
    ks: Sequence[int],
    seeds: int,
    scoring_cfg: tuple[rs.Scorer, int, int],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    placeholder = rs.placeholder_region()
    defaults = {"placeholder": placeholder}
    return {
        "ks": list(ks),
        "seeds": seeds,
        "repos": {p.name: {"dev_files": len(p.rows)} for p in data.pools},
        "skipped_repos": data.skipped,
        "n_drafts": len(data.drafts),
        "n_pairs": len(data.pairs),
        "constants": {
            "tiny_tokens": ff.TINY_TOKENS,
            "delegate_max_tokens": ff.DELEGATE_MAX_TOKENS,
            "cut_percentiles": list(ff.CUT_PERCENTILES),
            "mad_multiple": MAD_MULTIPLE,
            "trim_percent": TRIM_PERCENT,
            "anchor_percentile": ANCHOR_PERCENTILE,
            "weight_offset": br.WEIGHT_OFFSET,
        },
        "baseline": baseline,
        "features": features_report(data),
        "fits": fit_comparison(data, defaults, ks, seeds, scoring_cfg),
    }


def build_parser() -> argparse.ArgumentParser:
    import score_separation_run as ssr

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tables", type=Path)
    parser.add_argument("--baseline", type=Path, help="notes/sim-users.json")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--ks", default="1,2,3,4,5,6")
    parser.add_argument("--seeds", type=int, default=50)
    parser.add_argument("--per-repo", type=int, default=60)
    parser.add_argument("--variant-files", type=int, default=12)
    parser.add_argument("--score-seeds", type=int, default=4)
    parser.add_argument("--cross-files", type=int, default=10)
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
    ks = rs.parse_ks(args.ks)
    out = rs.plan_path(args.out)
    baseline_path = args.baseline or out.with_name("sim-users.json")
    data = load_all(args)
    cfg = (rs.region_scorer(), args.score_seeds, args.cross_files)
    baseline = baseline_from_sim(baseline_path)
    result = analyse(data, ks, args.seeds, cfg, baseline)
    text = dumps(result)
    out.write_text(text)
    if args.tables:
        rs.plan_path(args.tables).write_text(render(json.loads(text)))
    print(
        f"wrote {out} ({len(data.pools)} repos, {len(data.pairs)} pairs, {len(data.drafts)} drafts)"
    )
    if not args.check:
        return 0
    problems = rs.missing_n(result)
    if dumps(analyse(data, ks, args.seeds, cfg, baseline)) != text:
        problems.append("rerun differs")
    print("check: " + ("ok" if not problems else f"FAIL {problems}"))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
