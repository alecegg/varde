# ruff: noqa: E501, S112  (report text templates, skipped inputs)
"""Simulated users for calibrate-from-examples (deterministic, no model call).

    uv run python region_sim.py --language python --ks 1,2,3,4,5,6 --seeds 50 \
        --out notes/sim-users.json [--check]

A simulated user is one repo style: the dev-split files of a verified-corpus or
reference repo. Each simulation draws k of its files (fixed seed, ``0..N-1``),
runs ``baseline_region.calibrate``, and the result is checked for (1) stability
across resamples, (2) style sensitivity between repos, (3) real refactor pairs
(curated mined pairs) and (4) held-out good files versus degraded and
monolithic variants. Test-split and regression files are never read: paths are
filtered by ``splits.assignments`` before any blob is opened. Numbers are
reported with n; nothing is tuned to meet a target.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_run as ir
import baseline_measure as bm
import baseline_rank_run as rr
import baseline_region as br
import score_separation as ss
import splits

KEYS = tuple(br.FITTED.values())
MEASURES = tuple(br.FITTED)
MAX_K = 6
STABLE_SPREAD = 0.10
GOOD_TARGET = 0.90
MIN_DEV_FILES = 10
CORPUS_DEFAULT_PERCENTILE = 95
PLACEHOLDER_P0 = 2  # placeholder.toml has no p0; the schema probe and P+D2 use 2


Variant = tuple[tuple[int, ...], Any]  # (peak vector, scoring item)
Scorer = Callable[[Any, Sequence[int]], float]  # (item, region vector) -> score


class Pool(NamedTuple):
    """Dev-split files of one repo style: rows, peak vectors and scoring items."""

    name: str
    rows: list[list[dict[str, Any]]]
    peaks: list[tuple[int, ...]]
    items: list[Any]
    variants: dict[int, dict[str, Variant]]


class Scoring(NamedTuple):
    """Scored acceptance: score >= line accepts; only seeds below ``seeds`` score."""

    scorer: Scorer
    line: float
    seeds: int
    cross_files: int


class Run(NamedTuple):
    seed: int
    drawn: tuple[int, ...]
    region: tuple[int, ...]


class Data(NamedTuple):
    pools: list[Pool]
    corpus: dict[str, list[int]]
    placeholder: dict[str, int]
    drafts: list[Variant]
    pairs: list[dict[str, Any]]
    scorer: Scorer
    score_seeds: int
    cross_files: int
    skipped: dict[str, int]


# ---- pure helpers -----------------------------------------------------------


def parse_ks(text: str) -> list[int]:
    ks = sorted({int(part) for part in text.split(",") if part.strip()})
    if not ks or ks[0] < 1 or ks[-1] > MAX_K:
        raise ValueError(f"k must be within 1..{MAX_K}: {text}")
    return ks


def split_of(file_id: str) -> str:
    return splits.assignments([file_id])[file_id]


def draw(pool_size: int, k: int, seed: int) -> list[int]:
    """k distinct indexes of a pool; a pure function of (pool_size, k, seed)."""
    if pool_size < k + 2:
        raise ValueError(f"pool of {pool_size} files is too small for k={k}")
    rng = random.Random(f"region-sim:{seed}:{k}")  # noqa: S311 (seeded)
    return sorted(rng.sample(range(pool_size), k))


def trim(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{m: row.get(m) for m in MEASURES} for row in rows]


def peak_vector(rows: Sequence[Mapping[str, Any]]) -> tuple[int, ...]:
    """Largest function value per fitted measure, in ``KEYS`` order (0 when absent)."""
    return tuple(max(br.example_values(rows, m), default=0) for m in MEASURES)


def accepts(peaks: Sequence[int], region: Sequence[int]) -> bool:
    return all(p <= r for p, r in zip(peaks, region, strict=True))


def region_vector(region: Mapping[str, int]) -> tuple[int, ...]:
    return tuple(region[key] for key in KEYS)


def stat(value: float | None, n: int) -> dict[str, Any]:
    return {"n": n, "value": None if value is None else round(value, 4)}


def share(ok: int, n: int) -> dict[str, Any]:
    return stat(ok / n if n else None, n)


def relative_iqr(values: Sequence[int]) -> float | None:
    """(q75 - q25) / median; None without values or with a non-positive median."""
    q1, med, q3 = (br.nearest_rank(values, p) for p in (25, 50, 75))
    if med is None or med <= 0:
        return None
    return (q3 - q1) / med


def median_of(values: Sequence[float | None]) -> tuple[float | None, int]:
    known = sorted(v for v in values if v is not None)
    if not known:
        return None, 0
    mid = len(known) // 2
    value = known[mid] if len(known) % 2 else (known[mid - 1] + known[mid]) / 2
    return value, len(known)


def smallest_k(spread_by_k: Mapping[int, float | None]) -> int | None:
    return next(
        (
            k
            for k, s in sorted(spread_by_k.items())
            if s is not None and s <= STABLE_SPREAD
        ),
        None,
    )


def default_regions(
    placeholder: Mapping[str, int], corpus: Mapping[str, Sequence[int]]
) -> dict[str, dict[str, int]]:
    loose = dict(placeholder)
    for measure, key in br.FITTED.items():
        anchor = br.nearest_rank(corpus.get(measure, ()), CORPUS_DEFAULT_PERCENTILE)
        if anchor is not None:
            loose[key] = anchor
    return {
        "placeholder": dict(placeholder),
        f"corpus-q{CORPUS_DEFAULT_PERCENTILE}": loose,
    }


def excess(functions: Sequence[Sequence[int]], region: Sequence[int]) -> float:
    """Sum over functions and measures of the relative distance outside the region."""
    return sum(
        max(0, value - limit) / max(limit, 1)
        for values in functions
        for value, limit in zip(values, region, strict=True)
    )


def pair_outcome(
    pair: Mapping[str, Any], region: Sequence[int]
) -> tuple[bool, bool, bool]:
    """(after no further outside, before outside, strictly closer)."""
    before, after = excess(pair["before"], region), excess(pair["after"], region)
    return after <= before + 1e-9, before > 0, after < before - 1e-9


# ---- simulation -------------------------------------------------------------


def run_pool(
    pool: Pool,
    default: Mapping[str, int],
    corpus: Mapping[str, Sequence[int]],
    ks: Sequence[int],
    seeds: int,
) -> dict[int, list[Run]]:
    out: dict[int, list[Run]] = {}
    for k in ks:
        runs = []
        for seed in range(seeds):
            drawn = draw(len(pool.rows), k, seed)
            region = br.calibrate(default, [pool.rows[i] for i in drawn], corpus)
            runs.append(Run(seed, tuple(drawn), region_vector(region)))
        out[k] = runs
    return out


def tally_run(
    pool: Pool,
    others: Sequence[Pool],
    run: Run,
    drafts: Sequence[Variant],
    scoring: Scoring | None = None,
) -> dict[str, list[int]]:
    """[accepted-or-flagged, n] per label for one calibrated region.

    Strict labels accept a file when no function is outside the region;
    ``scored:`` labels accept it when its score under the region reaches the line.
    """
    drawn = set(run.drawn)
    out: dict[str, list[int]] = {}
    scored = scoring is not None and run.seed < scoring.seeds

    def add(label: str, peaks: Sequence[int], item: Any, accept: bool) -> None:
        inside = accepts(peaks, run.region)
        hit(out, label, inside if accept else not inside)
        if scored:
            ok = scoring.scorer(item, run.region) >= scoring.line
            hit(out, f"scored:{label}", ok if accept else not ok)

    for i in (i for i in range(len(pool.peaks)) if i not in drawn):
        add("good_heldout", pool.peaks[i], pool.items[i], True)
        for kind, (peaks, item) in pool.variants.get(i, {}).items():
            add(f"flagged:{kind}", peaks, item, False)
    cross_limit = scoring.cross_files if scoring else 0
    for other in others:
        for j, peaks in enumerate(other.peaks):
            if scored and j < cross_limit:
                add("cross_style", peaks, other.items[j], True)
            else:
                hit(out, "cross_style", accepts(peaks, run.region))
    for peaks, item in drafts:
        add("flagged:school_draft", peaks, item, False)
    return out


def hit(out: dict[str, list[int]], label: str, ok: bool) -> None:
    cell = out.setdefault(label, [0, 0])
    cell[0] += ok
    cell[1] += 1


def merge(total: dict[str, list[int]], part: Mapping[str, Sequence[int]]) -> None:
    for label, (hit, n) in part.items():
        cell = total.setdefault(label, [0, 0])
        cell[0] += hit
        cell[1] += n


def tally_view(total: Mapping[str, Sequence[int]]) -> dict[str, Any]:
    view = {label: share(hit, n) for label, (hit, n) in sorted(total.items())}
    for label in ("good_heldout", "scored:good_heldout"):
        good = view.get(label)
        if good and good["value"] is not None:
            view[f"meets_good_target:{label}"] = good["value"] >= GOOD_TARGET
    return view


def stability_view(
    all_runs: Mapping[str, Mapping[int, list[Run]]], ks: Sequence[int]
) -> dict[str, Any]:
    spreads: dict[int, dict[str, list[float | None]]] = {k: {} for k in ks}
    for by_k in all_runs.values():
        for k, runs in by_k.items():
            for index, key in enumerate(KEYS):
                values = [run.region[index] for run in runs]
                spreads[k].setdefault(key, []).append(relative_iqr(values))
    by_key = {key: {k: stat(*median_of(spreads[k][key])) for k in ks} for key in KEYS}
    overall = {
        k: stat(*median_of([by_key[key][k]["value"] for key in KEYS])) for k in ks
    }
    return {
        "median_spread": by_key,
        "overall_median_spread": overall,
        "smallest_k_at_or_below_10pct": {
            key: smallest_k({k: by_key[key][k]["value"] for k in ks}) for key in KEYS
        }
        | {"overall": smallest_k({k: overall[k]["value"] for k in ks})},
    }


def style_view(
    all_runs: Mapping[str, Mapping[int, list[Run]]],
    stability: Mapping[str, Any],
    ks: Sequence[int],
) -> dict[int, Any]:
    out: dict[int, Any] = {}
    for k in ks:
        entry: dict[str, Any] = {}
        for index, key in enumerate(KEYS):
            medians = [
                br.nearest_rank([r.region[index] for r in by_k[k]], 50) or 0
                for by_k in all_runs.values()
            ]
            between = relative_iqr(medians)
            within = stability["median_spread"][key][k]["value"]
            ratio = between / within if between is not None and within else None
            entry[key] = {
                "between_repo_spread": stat(between, len(medians)),
                "within_repo_spread": stat(within, len(medians)),
                "between_over_within": stat(ratio, len(medians)),
            }
        out[k] = entry
    return out


def accept_views(
    pools: Sequence[Pool],
    all_runs: Mapping[str, Mapping[int, list[Run]]],
    default_vector: Sequence[int],
    drafts: Sequence[Variant],
    ks: Sequence[int],
    scoring: Scoring | None = None,
) -> dict[str, Any]:
    by_k: dict[int, Any] = {}
    for k in ks:
        total: dict[str, list[int]] = {}
        for pool in pools:
            others = [o for o in pools if o is not pool]
            for run in all_runs[pool.name][k]:
                merge(total, tally_run(pool, others, run, drafts, scoring))
        by_k[k] = tally_view(total)
    default_total: dict[str, list[int]] = {}
    for pool in pools:
        others = [o for o in pools if o is not pool]
        merge(
            default_total,
            tally_run(
                pool, others, Run(-1, (), tuple(default_vector)), drafts, scoring
            ),
        )
    return {"repo_calibrated_by_k": by_k, "default_region": tally_view(default_total)}


def pair_cell(outcomes: Sequence[tuple[bool, bool, bool]]) -> dict[str, Any]:
    outside = [o for o in outcomes if o[1]]
    return {
        "no_further_outside": share(sum(o[0] for o in outcomes), len(outcomes)),
        "before_outside": share(len(outside), len(outcomes)),
        "strictly_closer_among_outside": share(
            sum(o[2] for o in outside), len(outside)
        ),
    }


def pair_view(
    pairs: Sequence[Mapping[str, Any]],
    all_runs: Mapping[str, Mapping[int, list[Run]]],
    default_vector: Sequence[int],
    ks: Sequence[int],
) -> dict[str, Any]:
    usable = [p for p in pairs if p["repo"] in all_runs]
    by_k = {
        k: pair_cell(
            [
                pair_outcome(p, run.region)
                for p in usable
                for run in all_runs[p["repo"]][k]
            ]
        )
        for k in ks
    }
    return {
        "n_pairs": len(usable),
        "repos": sorted({p["repo"] for p in usable}),
        "repo_calibrated_by_k": by_k,
        "default_region": pair_cell([pair_outcome(p, default_vector) for p in usable]),
    }


SWEEP_OFFSETS, SWEEP_PERCENTILES = (1, 2, 4, 8), (75, 90)


def median_shift(
    all_runs: Mapping[str, Mapping[int, list[Run]]],
    default_vector: Sequence[int],
    k: int,
) -> dict[str, Any]:
    """Median over repos and keys of |median threshold - default| / default."""
    shifts = []
    for by_k in all_runs.values():
        for index, base in enumerate(default_vector[: len(KEYS)]):
            middle = br.nearest_rank([r.region[index] for r in by_k[k]], 50)
            shifts.append(abs((middle or 0) - base) / max(base, 1))
    return stat(*median_of(shifts))


def constants_sweep(
    data: Data, default: Mapping[str, int], ks: Sequence[int], seeds: int
) -> dict[str, Any]:
    """Stability and responsiveness for other weight offsets and anchor percentiles.

    Rebinds the two ``baseline_region`` constants for the duration of each cell.
    """
    saved = br.WEIGHT_OFFSET, br.ANCHOR_PERCENTILE
    out: dict[str, Any] = {}
    try:
        for offset in SWEEP_OFFSETS:
            for percentile in SWEEP_PERCENTILES:
                br.WEIGHT_OFFSET, br.ANCHOR_PERCENTILE = offset, percentile
                runs = {
                    p.name: run_pool(p, default, data.corpus, ks, seeds)
                    for p in data.pools
                }
                stability = stability_view(runs, ks)
                vector = region_vector(default)
                out[f"offset{offset}-q{percentile}"] = {
                    "overall_median_spread": stability["overall_median_spread"],
                    "smallest_k": stability["smallest_k_at_or_below_10pct"]["overall"],
                    "median_shift_from_default": {
                        k: median_shift(runs, vector, k) for k in ks
                    },
                }
    finally:
        br.WEIGHT_OFFSET, br.ANCHOR_PERCENTILE = saved
    return out


def scoring_for(data: Data, default_vector: Sequence[int]) -> Scoring:
    """Line = 10th percentile of the pooled dev files' scores under the default."""
    scores = [data.scorer(item, default_vector) for p in data.pools for item in p.items]
    return Scoring(
        data.scorer,
        ss.cut_line(scores),
        data.score_seeds,
        data.cross_files,
    )


def simulate(data: Data, ks: Sequence[int], seeds: int) -> dict[str, Any]:
    defaults = default_regions(data.placeholder, data.corpus)
    result: dict[str, Any] = {
        "ks": list(ks),
        "seeds": seeds,
        "repos": {p.name: {"dev_files": len(p.rows)} for p in data.pools},
        "defaults": defaults,
        "constants": {
            "weight_offset": br.WEIGHT_OFFSET,
            "anchor_percentile": br.ANCHOR_PERCENTILE,
            "stable_spread": STABLE_SPREAD,
            "good_target": GOOD_TARGET,
        },
        "skipped_repos": data.skipped,
        "score_seeds": data.score_seeds,
        "by_default": {},
    }
    for name, default in defaults.items():
        all_runs = {
            p.name: run_pool(p, default, data.corpus, ks, seeds) for p in data.pools
        }
        stability = stability_view(all_runs, ks)
        vector = region_vector(default)
        scoring = scoring_for(data, vector)
        result["by_default"][name] = {
            "refactor_line": stat(scoring.line, sum(len(p.items) for p in data.pools)),
            "stability": stability,
            "style": style_view(all_runs, stability, ks),
            "held_out_and_variants": accept_views(
                data.pools, all_runs, vector, data.drafts, ks, scoring
            ),
            "mined_pairs": pair_view(data.pairs, all_runs, vector, ks),
        }
    result["constants_sweep"] = constants_sweep(
        data, defaults["placeholder"], ks, seeds
    )
    return result


def dumps(result: Mapping[str, Any]) -> str:
    return json.dumps(result, indent=1, sort_keys=True) + "\n"


def missing_n(node: Any) -> list[str]:
    """Paths of dicts that hold a ``value`` but no ``n``."""
    found: list[str] = []
    if isinstance(node, dict):
        if "value" in node and "n" not in node:
            found.append("value")
        for key, child in node.items():
            found += [f"{key}/{p}" for p in missing_n(child)]
    elif isinstance(node, list):
        for child in node:
            found += missing_n(child)
    return found


# ---- loading (I/O) ----------------------------------------------------------


def dev_paths(repo: str, paths: Sequence[str]) -> list[str]:
    """Candidate paths of the dev split only, in path-hash order."""
    ordered = ir.sample_paths(list(paths), len(paths))
    return [p for p in ordered if split_of(f"{repo}:{p}") == "dev"]


class SimFile(NamedTuple):
    source: str
    rows: list[dict[str, Any]]
    record: dict[str, Any]


def measure_file(blob: bytes) -> SimFile | None:
    import score_variants as sv

    source = blob.decode("utf-8", "replace")
    try:
        rows = bm.raw_measure_sources({"module.py": blob}, "python")["functions"]
        return SimFile(source, trim(rows), sv.measured_record(source))
    except Exception:  # noqa: BLE001 - a file the parser rejects is skipped
        return None


def read_dev_files(
    repo: str, paths: Sequence[str], read: Callable[[str], bytes | None], per_repo: int
) -> list[SimFile]:
    """Up to ``per_repo`` measured dev files; reads dev paths only."""
    files: list[SimFile] = []
    for path in dev_paths(repo, paths):
        if len(files) >= per_repo:
            break
        blob = read(path)
        if blob is None or not ir.MIN_BYTES <= len(blob) <= ir.MAX_BYTES:
            continue
        measured = measure_file(blob)
        if measured is not None:
            files.append(measured)
    return files


def variant_items(source: str) -> dict[str, Variant]:
    """Degraded and monolith variants of one source: (peak vector, record)."""
    import pd2_validation as pv
    import quality_degrade as qd
    import score_variants as sv

    makers: dict[str, Callable[[str], str | None]] = dict(qd.DEGRADATIONS)
    makers["monolith"] = pv.inline_to_monolith
    unchanged = qd.identity(source)
    found: dict[str, Variant] = {}
    for kind, make in makers.items():
        try:
            text = make(source)
            if text is None or text == unchanged:
                continue
            found[kind] = (
                peak_vector(ir.rows_of_source(text)),
                sv.measured_record(text),
            )
        except Exception:  # noqa: BLE001 - degradations that cannot apply are skipped
            continue
    return found


def build_pool(name: str, files: Sequence[SimFile], variant_files: int) -> Pool:
    variants = {
        i: variant_items(files[i].source) for i in range(min(variant_files, len(files)))
    }
    rows = [f.rows for f in files]
    return Pool(
        name, rows, [peak_vector(r) for r in rows], [f.record for f in files], variants
    )


def git_reader(checkout: Path, sha: str) -> Callable[[str], bytes | None]:
    def read(path: str) -> bytes | None:
        try:
            return ir.git_out(checkout, "show", f"{sha}:{path}")
        except Exception:  # noqa: BLE001 - unreadable blob
            return None

    return read


def file_reader(root: Path) -> Callable[[str], bytes | None]:
    def read(path: str) -> bytes | None:
        file = root / path
        return file.read_bytes() if file.is_file() else None

    return read


def load_pools(
    args: argparse.Namespace,
) -> tuple[list[Pool], dict[str, list[int]], dict[str, int]]:
    pools: list[Pool] = []
    skipped: dict[str, int] = {}
    corpus: dict[str, list[int]] = {m: [] for m in MEASURES}
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
        files = read_dev_files(
            repo["name"], paths, git_reader(checkout, sha), args.per_repo
        )
        for file in files:
            for m in MEASURES:
                corpus[m] += br.example_values(file.rows, m)
        if len(files) >= MIN_DEV_FILES:
            pools.append(build_pool(repo["name"], files, args.variant_files))
        else:
            skipped[repo["name"]] = len(files)
    for root in args.reference_repos:
        if not root.is_dir():
            continue
        name = f"ref/{root.name}"
        files = read_dev_files(
            name, rr.listed_paths(root), file_reader(root), args.per_repo
        )
        if len(files) >= MIN_DEV_FILES:
            pools.append(build_pool(name, files, args.variant_files))
        else:
            skipped[name] = len(files)
    return pools, corpus, skipped


def load_drafts(run_states: Sequence[Path]) -> list[Variant]:
    import score_separation_run as ssr
    import score_variants as sv

    sources = ssr.monolith_sources(run_states)
    return [
        (peak_vector(ir.rows_of_source(code)), sv.measured_record(code))
        for _, code in sorted(sources.items())
    ]


def region_scorer() -> Scorer:
    """Score of a record under the placeholder calibration with region thresholds."""
    from dataclasses import replace

    import scorer_candidates as sc

    base = bm.load_calibration(bm.DEFAULT_CALIBRATION)
    spec = sc.Spec("placeholder")
    micro = 1_000_000
    language = base.languages["python"]

    def score(record: Any, region: Sequence[int]) -> float:
        tuned = {
            **language.parameters,
            **{k: v * micro for k, v in zip(KEYS, region, strict=True)},
        }
        calibration = replace(
            base,
            languages={**base.languages, "python": replace(language, parameters=tuned)},
        )
        return sc.candidate_score(record, calibration, spec)

    return score


def load_pairs() -> list[dict[str, Any]]:
    """Curated mined pairs as per-function value tuples before and after."""
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
        sides = [
            [tuple(r[m] or 0 for m in MEASURES) for r in ir.rows_of_source(s)]
            for s in (before, after)
        ]
        found.append({"repo": pair["repo"], "before": sides[0], "after": sides[1]})
    return found


def placeholder_region() -> dict[str, int]:
    import tomllib

    table = tomllib.loads(br.DEFAULT_CALIBRATION.read_text())["language"]["python"]
    region = {k: v for k, v in table.items() if isinstance(v, int)}
    return {**region, "p0": PLACEHOLDER_P0}


# ---- report -----------------------------------------------------------------


def pct(node: Mapping[str, Any] | None) -> str:
    if not node or node["value"] is None:
        return "-"
    return f"{100 * node['value']:.0f}% (n={node['n']})"


def num(node: Mapping[str, Any] | None) -> str:
    if not node or node["value"] is None:
        return "-"
    return f"{node['value']:.2f} (n={node['n']})"


def render(result: Mapping[str, Any]) -> str:
    ks = result["ks"]
    lines = [
        "# Simulated users for calibrate-from-examples",
        "",
        (
            f"Repos (dev-split files): {json.dumps(result['repos'], sort_keys=True)}; "
            f"k = {ks}; seeds 0..{result['seeds'] - 1}; weight offset "
            f"{result['constants']['weight_offset']}, anchor "
            f"q{result['constants']['anchor_percentile']}."
        ),
    ]
    for name, view in result["by_default"].items():
        lines += [
            "",
            f"## Default region: {name} (refactor line {num(view['refactor_line'])})",
            f"{json.dumps(result['defaults'][name], sort_keys=True)}",
            "",
        ]
        lines += stability_lines(view["stability"], ks)
        lines += style_lines(view["style"], view["held_out_and_variants"], ks)
        lines += pair_lines(view["mined_pairs"], ks)
        lines += held_out_lines(view["held_out_and_variants"], ks)
    lines += [""] + sweep_lines(result["constants_sweep"], ks)
    return "\n".join(lines) + "\n"


def sweep_lines(sweep: Mapping[str, Any], ks: Sequence[int]) -> list[str]:
    lines = [
        "## Constants sweep (placeholder default; spread / median shift from default)",
        "",
        "offset, anchor | "
        + " | ".join(f"k={k}" for k in ks)
        + " | smallest k at <=10%",
        "--- | " + " | ".join("---" for _ in ks) + " | ---",
    ]
    for label, cell in sweep.items():
        cells = " | ".join(
            f"{num(cell['overall_median_spread'][k])} / {num(cell['median_shift_from_default'][k])}"
            for k in ks
        )
        lines.append(f"{label} | {cells} | {cell['smallest_k']}")
    return [*lines, ""]


def stability_lines(stability: Mapping[str, Any], ks: Sequence[int]) -> list[str]:
    lines = [
        "### Stability (median relative IQR of thresholds across resamples, median over repos)",
        "",
        "measure key | " + " | ".join(f"k={k}" for k in ks) + " | smallest k at <=10%",
    ]
    lines.append("--- | " + " | ".join("---" for _ in ks) + " | ---")
    smallest = stability["smallest_k_at_or_below_10pct"]
    for key in KEYS:
        cells = " | ".join(num(stability["median_spread"][key][k]) for k in ks)
        lines.append(f"{key} | {cells} | {smallest[key]}")
    overall = " | ".join(num(stability["overall_median_spread"][k]) for k in ks)
    lines += [f"all keys (median) | {overall} | {smallest['overall']}", ""]
    return lines


def style_lines(
    style: Mapping[Any, Any], held: Mapping[str, Any], ks: Sequence[int]
) -> list[str]:
    lines = [
        "### Style sensitivity",
        "",
        "k | between/within spread per key | own held-out accepted (strict / scored) | other repos' files accepted (strict / scored)",
        "--- | --- | --- | ---",
    ]
    rows = [(str(k), held["repo_calibrated_by_k"][k], k) for k in ks]
    rows.append(("default region", held["default_region"], None))
    for label, cell, k in rows:
        ratios = (
            ", ".join(
                f"{key}={num(style[k][key]['between_over_within'])}" for key in KEYS
            )
            if k
            else "-"
        )
        own = (
            f"{pct(cell.get('good_heldout'))} / {pct(cell.get('scored:good_heldout'))}"
        )
        cross = (
            f"{pct(cell.get('cross_style'))} / {pct(cell.get('scored:cross_style'))}"
        )
        lines.append(f"{label} | {ratios} | {own} | {cross}")
    return [*lines, ""]


def pair_lines(pairs: Mapping[str, Any], ks: Sequence[int]) -> list[str]:
    lines = [
        f"### Curated mined refactor pairs ({pairs['n_pairs']} pairs; repos {pairs['repos']}; repo-calibrated n counts pair x resample)",
        "",
        "region | after no further outside than before | before outside | strictly closer (of outside)",
        "--- | --- | --- | ---",
    ]
    rows = [(f"repo-calibrated k={k}", pairs["repo_calibrated_by_k"][k]) for k in ks]
    rows.append(("default", pairs["default_region"]))
    for label, cell in rows:
        lines.append(
            f"{label} | {pct(cell['no_further_outside'])} | {pct(cell['before_outside'])} | "
            f"{pct(cell['strictly_closer_among_outside'])}"
        )
    return [*lines, ""]


def held_out_lines(held: Mapping[str, Any], ks: Sequence[int]) -> list[str]:
    cells = [*held["repo_calibrated_by_k"].values(), held["default_region"]]
    names = {label.removeprefix("scored:") for c in cells for label in c}
    kinds = sorted(
        n.removeprefix("flagged:") for n in names if n.startswith("flagged:")
    )
    lines = [
        "### Held-out good accepted and variants flagged (strict / scored)",
        "",
        "region | good accepted | " + " | ".join(kinds),
        "--- | --- | " + " | ".join("---" for _ in kinds),
    ]
    rows = [(f"repo-calibrated k={k}", held["repo_calibrated_by_k"][k]) for k in ks]
    rows.append(("default", held["default_region"]))
    for label, cell in rows:
        flagged = " | ".join(
            f"{pct(cell.get('flagged:' + k))} / {pct(cell.get('scored:flagged:' + k))}"
            for k in kinds
        )
        good = (
            f"{pct(cell.get('good_heldout'))} / {pct(cell.get('scored:good_heldout'))}"
        )
        lines.append(f"{label} | {good} | {flagged}")
    return [*lines, "Target: held-out good accepted at least 90%.", ""]


# ---- CLI --------------------------------------------------------------------


def plan_path(path: Path) -> Path:
    """``notes/...`` resolves inside the plan folder, anything else as given."""
    if path.is_absolute() or path.parts[:1] != ("notes",):
        return path
    return ssr_plan_dir() / path


def ssr_plan_dir() -> Path:
    import score_separation_run as ssr

    return ssr.PLAN_NOTES.parents[1]


def build_parser() -> argparse.ArgumentParser:
    import score_separation_run as ssr

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="python")
    parser.add_argument("--ks", default="1,2,3,4,5,6")
    parser.add_argument("--seeds", type=int, default=50)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--per-repo", type=int, default=60)
    parser.add_argument("--variant-files", type=int, default=12)
    parser.add_argument("--score-seeds", type=int, default=20)
    parser.add_argument("--cross-files", type=int, default=15)
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
    if args.language != "python":
        print("only python has a verified corpus with mined pairs", file=sys.stderr)
        return 2
    ks = parse_ks(args.ks)
    pools, corpus, skipped = load_pools(args)
    data = Data(
        pools,
        corpus,
        placeholder_region(),
        load_drafts(args.run_state),
        load_pairs(),
        region_scorer(),
        args.score_seeds,
        args.cross_files,
        skipped,
    )
    result = simulate(data, ks, args.seeds)
    text = dumps(result)
    out = plan_path(args.out)
    out.write_text(text)
    out.with_suffix(".md").write_text(render(result))
    print(
        f"wrote {out} ({len(pools)} repos, {len(data.pairs)} pairs, {len(data.drafts)} drafts)"
    )
    if not args.check:
        return 0
    problems = missing_n(result)
    if dumps(simulate(data, ks, args.seeds)) != text:
        problems.append("rerun differs")
    print("check: " + ("ok" if not problems else f"FAIL {problems}"))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
